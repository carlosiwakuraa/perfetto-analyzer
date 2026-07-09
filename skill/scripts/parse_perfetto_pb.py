#!/usr/bin/env python3
"""Parse de um arquivo .pb do Perfetto usando a Trace Processor Python API."""

import argparse
import json
import sys
import os


def try_import():
    try:
        from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig
        return TraceProcessor, TraceProcessorConfig
    except ImportError:
        print("ERRO: Biblioteca 'perfetto' não instalada.", file=sys.stderr)
        print("Execute: pip install perfetto", file=sys.stderr)
        sys.exit(1)


def query_to_dicts(tp, sql):
    """Executa SQL e retorna lista de dicts. Retorna [] em caso de erro."""
    try:
        result = tp.query(sql)
        rows = []
        for row in result:
            rows.append({col: getattr(row, col) for col in result.column_names})
        return rows
    except Exception as e:
        # Tabela não existe neste trace (ex: heap_profile sem heapprofd)
        return []


def extract_memory(tp):
    native_allocs = query_to_dicts(tp, """
        SELECT
            spf.name AS function_name,
            spf.mapping_name,
            SUM(CASE WHEN hpa.size > 0 THEN hpa.size ELSE 0 END) AS alloc_bytes,
            SUM(CASE WHEN hpa.size < 0 THEN -hpa.size ELSE 0 END) AS freed_bytes,
            SUM(CASE WHEN hpa.count > 0 THEN hpa.count ELSE 0 END) AS alloc_count
        FROM heap_profile_allocation hpa
        JOIN stack_profile_callsite spc ON spc.id = hpa.callsite_id
        JOIN stack_profile_frame spf ON spf.id = spc.frame_id
        GROUP BY spf.name, spf.mapping_name
        ORDER BY alloc_bytes DESC
        LIMIT 20
    """)

    for alloc in native_allocs:
        alloc["unreleased_bytes"] = alloc.get("alloc_bytes", 0) - alloc.get("freed_bytes", 0)

    art_objects = query_to_dicts(tp, """
        SELECT
            hgc.name AS type_name,
            COUNT(*) AS instance_count,
            SUM(hgo.self_size) AS total_size
        FROM heap_graph_object hgo
        JOIN heap_graph_class hgc ON hgc.id = hgo.type_id
        WHERE hgo.reachable = 1
        GROUP BY hgc.name
        ORDER BY total_size DESC
        LIMIT 20
    """)

    return {
        "native_top_allocators": native_allocs,
        "art_retained_objects": art_objects,
    }


def extract_cpu(tp):
    sched_summary = query_to_dicts(tp, """
        SELECT
            p.name AS process_name,
            SUM(sched.dur) / 1e9 AS total_cpu_seconds,
            COUNT(*) AS context_switches
        FROM sched
        JOIN thread t ON t.utid = sched.utid
        JOIN process p ON p.upid = t.upid
        WHERE p.name IS NOT NULL
        GROUP BY p.name
        ORDER BY total_cpu_seconds DESC
        LIMIT 15
    """)

    cpu_freq = query_to_dicts(tp, """
        SELECT
            cct.cpu,
            AVG(c.value) AS avg_freq_mhz,
            MAX(c.value) AS max_freq_mhz
        FROM counter c
        JOIN cpu_counter_track cct ON cct.id = c.track_id
        WHERE cct.name = 'cpufreq'
        GROUP BY cct.cpu
        ORDER BY cct.cpu
    """)

    # Top frame nativo de cada sample (contexto de baixo nível)
    top_callstacks = query_to_dicts(tp, """
        SELECT
            spf.name AS function_name,
            t.name AS thread_name,
            p.name AS process_name,
            COUNT(*) AS sample_count
        FROM perf_sample ps
        JOIN stack_profile_callsite spc ON spc.id = ps.callsite_id
        JOIN stack_profile_frame spf ON spf.id = spc.frame_id
        LEFT JOIN thread t ON t.utid = ps.utid
        LEFT JOIN process p ON p.upid = t.upid
        GROUP BY spf.name, t.name, p.name
        ORDER BY sample_count DESC
        LIMIT 20
    """)

    # Frames Kotlin/Java em toda a cadeia do callsite (identifica ofensores reais)
    jvm_callstacks = query_to_dicts(tp, """
        WITH RECURSIVE callsite_chain(sample_id, frame_id, parent_id, depth) AS (
            SELECT ps.id, spc.frame_id, spc.parent_id, 1
            FROM perf_sample ps
            JOIN stack_profile_callsite spc ON spc.id = ps.callsite_id
            UNION ALL
            SELECT cc.sample_id, spc.frame_id, spc.parent_id, cc.depth + 1
            FROM callsite_chain cc
            JOIN stack_profile_callsite spc ON spc.id = cc.parent_id
            WHERE cc.depth < 60
        )
        SELECT
            spf.name AS function_name,
            spm.name AS mapping_name,
            COUNT(DISTINCT cc.sample_id) AS sample_count
        FROM callsite_chain cc
        JOIN stack_profile_frame spf ON spf.id = cc.frame_id
        LEFT JOIN stack_profile_mapping spm ON spm.id = spf.mapping
        WHERE spf.name LIKE 'com.%'
           OR spf.name LIKE 'kotlin.%'
           OR spf.name LIKE 'androidx.%'
           OR spf.name LIKE 'org.jetbrains.%'
        GROUP BY spf.name, spm.name
        ORDER BY sample_count DESC
        LIMIT 40
    """)

    return {
        "scheduling_summary": sched_summary,
        "cpu_frequency": cpu_freq,
        "top_cpu_callstacks": top_callstacks,
        "jvm_callstacks": jvm_callstacks,
        # preenchido em main() após saber o --package
        "app_callstacks": [],
    }


def extract_frames(tp):
    frames = query_to_dicts(tp, """
        SELECT
            aft.layer_name,
            aft.present_type,
            aft.on_time_finish,
            aft.jank_type,
            (aft.ts_end - aft.ts) / 1e6 AS duration_ms
        FROM actual_frame_timeline_slice aft
        ORDER BY aft.ts
        LIMIT 5000
    """)

    if not frames:
        # Fallback para Android < 12 ou devices sem frame timeline.
        # O nome do slice varia por versão: 'Choreographer#doFrame', 'Choreographer#doFrame 12345', etc.
        frames = query_to_dicts(tp, """
            SELECT
                s.name,
                s.dur / 1e6 AS duration_ms
            FROM slice s
            WHERE s.name LIKE 'Choreographer#doFrame%'
               OR s.name LIKE '%DrawFrame%'
               OR s.name = 'doFrame'
            ORDER BY s.ts
            LIMIT 5000
        """)

    total = len(frames)
    durations = [f.get("duration_ms", 0) for f in frames if f.get("duration_ms")]
    dropped = sum(
        1 for f in frames
        if f.get("on_time_finish") == 0 or f.get("duration_ms", 0) > 16.67
    )

    percentiles = {}
    if durations:
        s = sorted(durations)
        n = len(s)
        percentiles = {
            "p50": round(s[int(n * 0.50)], 2),
            "p95": round(s[int(n * 0.95)], 2),
            "p99": round(s[min(int(n * 0.99), n - 1)], 2),
            "max": round(max(s), 2),
        }

    jank_causes = {}
    for f in frames:
        j = str(f.get("jank_type", ""))
        if j and j not in ("None", "0", ""):
            jank_causes[j] = jank_causes.get(j, 0) + 1

    # Callstacks JVM que ocorreram durante frames janked — identifica o ofensor do jank
    jank_jvm_callstacks = query_to_dicts(tp, """
        WITH jank_windows AS (
            SELECT aft.ts AS frame_start, aft.ts_end AS frame_end
            FROM actual_frame_timeline_slice aft
            WHERE aft.on_time_finish = 0
        ),
        jank_samples AS (
            SELECT DISTINCT ps.id AS sample_id
            FROM perf_sample ps
            JOIN jank_windows jw ON ps.ts >= jw.frame_start AND ps.ts <= jw.frame_end
        ),
        callsite_chain(sample_id, frame_id, parent_id, depth) AS (
            SELECT js.sample_id, spc.frame_id, spc.parent_id, 1
            FROM jank_samples js
            JOIN perf_sample ps ON ps.id = js.sample_id
            JOIN stack_profile_callsite spc ON spc.id = ps.callsite_id
            UNION ALL
            SELECT cc.sample_id, spc.frame_id, spc.parent_id, cc.depth + 1
            FROM callsite_chain cc
            JOIN stack_profile_callsite spc ON spc.id = cc.parent_id
            WHERE cc.depth < 60
        )
        SELECT
            spf.name AS function_name,
            COUNT(DISTINCT cc.sample_id) AS sample_count
        FROM callsite_chain cc
        JOIN stack_profile_frame spf ON spf.id = cc.frame_id
        WHERE spf.name LIKE 'com.%'
           OR spf.name LIKE 'kotlin.%'
           OR spf.name LIKE 'androidx.%'
           OR spf.name LIKE 'org.jetbrains.%'
        GROUP BY spf.name
        ORDER BY sample_count DESC
        LIMIT 20
    """)

    return {
        "total_frames": total,
        "dropped_frames": dropped,
        "dropped_pct": round(dropped / total * 100, 2) if total else 0,
        "frame_duration_percentiles_ms": percentiles,
        "jank_causes": jank_causes,
        "jank_jvm_callstacks": jank_jvm_callstacks,
        # preenchido em main() após saber o --package
        "jank_app_callstacks": [],
    }


def extract_battery(tp):
    battery_counters = query_to_dicts(tp, """
        SELECT
            ct.name AS counter_name,
            MIN(c.value) AS min_value,
            MAX(c.value) AS max_value,
            MAX(c.value) - MIN(c.value) AS delta
        FROM counter c
        JOIN counter_track ct ON ct.id = c.track_id
        WHERE ct.name IN (
            'batt_charge_uah', 'batt_capacity_pct', 'batt_current_ua',
            'batt_voltage_uv', 'BatteryStats.Batt.Charge.uah'
        )
        GROUP BY ct.name
    """)

    power_rails = query_to_dicts(tp, """
        SELECT
            ct.name AS rail_name,
            SUM(c.value) / 1e3 AS total_mw
        FROM counter c
        JOIN counter_track ct ON ct.id = c.track_id
        WHERE ct.name LIKE 'power.rails.%'
        GROUP BY ct.name
        ORDER BY total_mw DESC
        LIMIT 10
    """)

    return {
        "battery_counters": battery_counters,
        "power_rails": power_rails,
    }


def get_trace_duration(tp):
    for table in ("sched", "slice", "counter"):
        rows = query_to_dicts(tp, f"SELECT (MAX(ts) - MIN(ts)) / 1e9 AS duration_seconds FROM {table}")
        if rows and rows[0].get("duration_seconds"):
            return rows[0]["duration_seconds"]
    return 0


def _app_prefix(package):
    """Deriva o prefixo de pacote para filtrar classes do app.

    'com.example.app.debug' → 'com.example.app'
    Remove sufixos de build variant conhecidos para que o LIKE funcione
    contra nomes de classe como 'com.example.app.feature.HomeScreen'.
    """
    BUILD_SUFFIXES = {"debug", "release", "staging", "demo", "qa", "prod", "internal", "beta"}
    parts = package.split(".")
    while parts and parts[-1].lower() in BUILD_SUFFIXES:
        parts.pop()
    return ".".join(parts)


def extract_app_callstacks(tp, package):
    """Para cada sample de CPU, encontra o frame mais superficial que pertence ao app.

    Isso responde: 'qual função do MEU código estava ativa quando a amostra foi colhida?'
    O frame mais superficial (menor depth) é o mais próximo de onde a CPU estava,
    dentro do código do app — ou seja, o ponto de entrada que chamou as APIs do framework.
    """
    if not package:
        return []

    prefix = _app_prefix(package)

    return query_to_dicts(tp, f"""
        WITH RECURSIVE callsite_chain(sample_id, frame_id, parent_id, depth) AS (
            SELECT ps.id, spc.frame_id, spc.parent_id, 1
            FROM perf_sample ps
            JOIN thread t ON t.utid = ps.utid
            JOIN process p ON p.upid = t.upid
            JOIN stack_profile_callsite spc ON spc.id = ps.callsite_id
            WHERE p.name = '{package}'
            UNION ALL
            SELECT cc.sample_id, spc.frame_id, spc.parent_id, cc.depth + 1
            FROM callsite_chain cc
            JOIN stack_profile_callsite spc ON spc.id = cc.parent_id
            WHERE cc.depth < 60
        ),
        top_app AS (
            SELECT cc.sample_id, MIN(cc.depth) AS min_depth
            FROM callsite_chain cc
            JOIN stack_profile_frame spf ON spf.id = cc.frame_id
            WHERE spf.name LIKE '{prefix}.%'
            GROUP BY cc.sample_id
        )
        SELECT
            spf.name AS function_name,
            t.name AS thread_name,
            COUNT(DISTINCT cc.sample_id) AS sample_count
        FROM callsite_chain cc
        JOIN top_app ta ON ta.sample_id = cc.sample_id AND cc.depth = ta.min_depth
        JOIN stack_profile_frame spf ON spf.id = cc.frame_id
        JOIN perf_sample ps ON ps.id = cc.sample_id
        JOIN thread t ON t.utid = ps.utid
        GROUP BY spf.name, t.name
        ORDER BY sample_count DESC
        LIMIT 25
    """)


def main():
    parser = argparse.ArgumentParser(description="Parse de trace Perfetto")
    parser.add_argument("--input", required=True, help="Arquivo .pb")
    parser.add_argument("--output", default="/tmp/perfetto_parsed.json", help="JSON de saída")
    parser.add_argument("--package", default="", help="Package do app (ex: com.example.app)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERRO: Arquivo não encontrado: {args.input}", file=sys.stderr)
        sys.exit(1)

    TraceProcessor, TraceProcessorConfig = try_import()

    size_mb = os.path.getsize(args.input) / 1024 / 1024
    print(f"Trace: {args.input} ({size_mb:.1f} MB)")

    # load_timeout precisa ser proporcional ao tamanho do trace
    # padrão de 2s é insuficiente para traces > ~5 MB
    timeout_seconds = max(60, int(size_mb * 2))
    print(f"Abrindo trace (timeout: {timeout_seconds}s)...")

    config = TraceProcessorConfig(load_timeout=timeout_seconds)
    try:
        tp = TraceProcessor(trace=args.input, config=config)
    except Exception as e:
        print(f"ERRO ao abrir trace: {e}", file=sys.stderr)
        print("Verifique se o arquivo .pb não está corrompido.", file=sys.stderr)
        sys.exit(1)

    print("Extraindo memória...")
    memory = extract_memory(tp)

    print("Extraindo CPU...")
    cpu = extract_cpu(tp)

    print("Extraindo frames...")
    frames = extract_frames(tp)

    print("Extraindo battery...")
    battery = extract_battery(tp)

    duration = get_trace_duration(tp)

    if args.package:
        print("Extraindo callstacks do app...")
        app_stacks = extract_app_callstacks(tp, args.package)
        cpu["app_callstacks"] = app_stacks

        # Para frames janked: mesma lógica mas restrita à janela de tempo do jank
        prefix = _app_prefix(args.package)
        pkg = args.package
        jank_app = query_to_dicts(tp, f"""
            WITH jank_windows AS (
                SELECT aft.ts AS frame_start, aft.ts_end AS frame_end
                FROM actual_frame_timeline_slice aft
                WHERE aft.on_time_finish = 0
            ),
            jank_samples AS (
                SELECT DISTINCT ps.id AS sample_id
                FROM perf_sample ps
                JOIN thread t ON t.utid = ps.utid
                JOIN process p ON p.upid = t.upid
                JOIN jank_windows jw ON ps.ts >= jw.frame_start AND ps.ts <= jw.frame_end
                WHERE p.name = '{pkg}'
            ),
            callsite_chain(sample_id, frame_id, parent_id, depth) AS (
                SELECT js.sample_id, spc.frame_id, spc.parent_id, 1
                FROM jank_samples js
                JOIN perf_sample ps ON ps.id = js.sample_id
                JOIN stack_profile_callsite spc ON spc.id = ps.callsite_id
                UNION ALL
                SELECT cc.sample_id, spc.frame_id, spc.parent_id, cc.depth + 1
                FROM callsite_chain cc
                JOIN stack_profile_callsite spc ON spc.id = cc.parent_id
                WHERE cc.depth < 60
            ),
            top_app AS (
                SELECT cc.sample_id, MIN(cc.depth) AS min_depth
                FROM callsite_chain cc
                JOIN stack_profile_frame spf ON spf.id = cc.frame_id
                WHERE spf.name LIKE '{prefix}.%'
                GROUP BY cc.sample_id
            )
            SELECT
                spf.name AS function_name,
                t.name AS thread_name,
                COUNT(DISTINCT cc.sample_id) AS sample_count
            FROM callsite_chain cc
            JOIN top_app ta ON ta.sample_id = cc.sample_id AND cc.depth = ta.min_depth
            JOIN stack_profile_frame spf ON spf.id = cc.frame_id
            JOIN perf_sample ps ON ps.id = cc.sample_id
            JOIN thread t ON t.utid = ps.utid
            GROUP BY spf.name, t.name
            ORDER BY sample_count DESC
            LIMIT 20
        """)
        frames["jank_app_callstacks"] = jank_app

    tp.close()

    output = {
        "trace_duration_seconds": round(float(duration), 2),
        "memory": memory,
        "cpu": cpu,
        "frames": frames,
        "battery": battery,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nDados extraídos: {args.output}")


if __name__ == "__main__":
    main()
