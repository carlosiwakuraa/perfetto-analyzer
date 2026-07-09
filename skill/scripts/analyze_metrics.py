#!/usr/bin/env python3
"""Analisa métricas brutas do trace e gera insights acionáveis."""

import argparse
import json
import sys
import os

# Thresholds de referência (Android best practices)
THRESHOLDS = {
    "frame_p50_ms": 8.0,       # 120fps → 8.3ms, 60fps → 16.7ms
    "frame_p95_ms": 16.67,     # Máximo para experiência fluida a 60fps
    "frame_p99_ms": 32.0,      # Tolerável mas problemático
    "dropped_pct_warn": 1.0,   # >1% dropped é sinal de jank
    "dropped_pct_critical": 5.0,
    "heap_churn_ratio": 10.0,  # total_alloc / unreleased > 10 = churn alto
    "cpu_main_thread_pct": 20.0,  # Main thread não deve ter > 20% do CPU total
}


def analyze_memory(memory_data):
    issues = []
    insights = []
    native_allocs = memory_data.get("native_top_allocators", [])
    art_objects = memory_data.get("art_retained_objects", [])

    total_unreleased = sum(a.get("unreleased_bytes", 0) for a in native_allocs)
    total_allocated = sum(a.get("total_bytes", 0) for a in native_allocs)

    if total_unreleased > 0:
        unreleased_mb = total_unreleased / 1024 / 1024
        insights.append(f"Heap nativo total não-liberado: {unreleased_mb:.1f} MB")

    # Detectar heap churn
    if total_unreleased > 0 and total_allocated > 0:
        churn_ratio = total_allocated / total_unreleased
        if churn_ratio > THRESHOLDS["heap_churn_ratio"]:
            issues.append({
                "severity": "warning",
                "category": "memory",
                "title": "Heap Churn Elevado",
                "detail": f"Ratio alocado/não-liberado = {churn_ratio:.1f}x. "
                          f"Muitas alocações temporárias causam GC frequente e stuttering.",
                "action": "Revisar pools de objetos, reutilizar buffers, evitar alocações em hot paths.",
            })

    # Top callstacks como insights
    top_3 = native_allocs[:3]
    for i, alloc in enumerate(top_3):
        mb = alloc.get("unreleased_bytes", 0) / 1024 / 1024
        stack = alloc.get("stack", [])
        top_fn = stack[0] if stack else "desconhecida"
        if mb > 1.0:
            insights.append(f"Top alocador #{i+1}: {top_fn} ({mb:.1f} MB não-liberados)")

    # ART objects
    total_art_mb = sum(o.get("total_size", 0) for o in art_objects) / 1024 / 1024
    if total_art_mb > 50:
        issues.append({
            "severity": "warning",
            "category": "memory",
            "title": "Muitos Objetos Java Retidos",
            "detail": f"{total_art_mb:.0f} MB de objetos Java/Kotlin retidos no heap. "
                      f"Pode indicar memory leak ou referências fortes desnecessárias.",
            "action": "Verificar WeakReference, LiveData, ViewModel, e Listeners que podem vazar.",
        })

    return {
        "issues": issues,
        "insights": insights,
        "summary": {
            "total_unreleased_mb": round(total_unreleased / 1024 / 1024, 2),
            "total_allocated_mb": round(total_allocated / 1024 / 1024, 2),
            "total_art_retained_mb": round(total_art_mb, 2),
            "top_native_allocators": native_allocs[:10],
            "top_art_objects": art_objects[:10],
        },
    }


def analyze_cpu(cpu_data):
    issues = []
    insights = []
    sched = cpu_data.get("scheduling_summary", [])
    samples = cpu_data.get("top_cpu_callstacks", [])
    freq = cpu_data.get("cpu_frequency", [])

    total_cpu_time = sum(p.get("total_cpu_seconds", 0) for p in sched)

    # Identificar o processo do app (o maior não-sistema entre os top processos)
    # Processos de sistema comuns a excluir da análise de dominância
    SYSTEM_PROCS = {"/system/bin/", "/vendor/bin/", "kworker", "kswapd", "system_server",
                    "com.android.systemui", "com.android.phone", "traced_perf", "traced_probes"}

    def is_system(name):
        return any(s in name for s in SYSTEM_PROCS)

    # Callstacks filtrados para o processo do app
    app_name = ""
    app_procs = [p for p in sched if not is_system(p.get("process_name", ""))]
    if app_procs:
        top_app = app_procs[0]
        app_name = top_app["process_name"]
        app_pct = top_app["total_cpu_seconds"] / total_cpu_time * 100 if total_cpu_time else 0
        insights.append(
            f"Processo com mais CPU: {top_app['process_name']} — "
            f"{top_app['total_cpu_seconds']:.2f}s ({app_pct:.1f}% do total)"
        )
        if app_pct > 40:
            # Identifica ofensores reais nos callstacks do app
            app_stacks = [s for s in samples if s.get("process_name") == app_name]
            top_offenders = app_stacks[:3]
            offender_lines = []
            for s in top_offenders:
                fn = s.get("function_name", "?")
                thread = s.get("thread_name", "?")
                count = s.get("sample_count", 0)
                offender_lines.append(f"`{fn}` ({thread}, {count} amostras)")
            offender_text = "; ".join(offender_lines) if offender_lines else "ver tabela de callstacks"

            issues.append({
                "severity": "warning",
                "category": "cpu",
                "title": f"App com Alto Uso de CPU ({app_pct:.0f}%)",
                "detail": f"{top_app['process_name']} consumiu {top_app['total_cpu_seconds']:.2f}s de CPU "
                          f"({app_pct:.0f}% do total). Principais ofensores: {offender_text}.",
                "action": "Investigar as funções listadas na tabela 'Top Funções por Amostras de CPU'. "
                          "Funções de ART interpreter indicam código Kotlin/Java não otimizado (Compose recomposição excessiva). "
                          "Funções em RenderThread indicam gargalo de GPU/composição. "
                          "Abrir o .pb no perfetto.dev/ui para flame graph interativo.",
            })

    # Context switches elevados
    total_switches = sum(p.get("context_switches", 0) for p in sched)
    if total_switches > 10000:
        insights.append(f"Total de context switches: {total_switches:,} — pode indicar contention entre threads")

    # Frequência de CPU — emuladores reportam 1-2 (escala relativa, não MHz)
    valid_freqs = [f for f in freq if f.get("avg_freq_mhz", 0) >= 100]
    if valid_freqs:
        overall_avg = sum(f["avg_freq_mhz"] for f in valid_freqs) / len(valid_freqs)
        insights.append(f"Frequência média de CPU: {overall_avg:.0f} MHz")

    # Detectar padrões problemáticos nos frames JVM
    jvm = cpu_data.get("jvm_callstacks", [])
    total_jvm_samples = max((j.get("sample_count", 0) for j in jvm), default=1)

    def jvm_hit(pattern):
        # max() para não duplicar quando múltiplos métodos da mesma classe aparecem no mesmo sample
        counts = [j["sample_count"] for j in jvm if pattern in j.get("function_name", "")]
        return max(counts) if counts else 0

    recomposer_hits = jvm_hit("Recomposer")
    snapshot_hits = jvm_hit("SnapshotStateObserver")
    coroutine_hits = jvm_hit("BaseContinuationImpl")

    if recomposer_hits > 0 or snapshot_hits > 0:
        pct = round(max(recomposer_hits, snapshot_hits) / total_jvm_samples * 100)
        issues.append({
            "severity": "warning",
            "category": "cpu",
            "title": f"Recomposição Excessiva do Compose ({pct}% das amostras JVM)",
            "detail": (
                f"O Recomposer aparece em {recomposer_hits} amostras e "
                f"SnapshotStateObserver em {snapshot_hits} amostras. "
                f"Indica que composables estão recompondo com frequência desnecessária."
            ),
            "action": (
                "1. Usar o Layout Inspector (Android Studio) → 'Recomposition Counts' para "
                "identificar quais composables recompõem mais. "
                "2. Envolver leituras de estado derivado em `remember { derivedStateOf {} }`. "
                "3. Garantir que lambdas passados a composables são estáveis (`@Stable`, "
                "`rememberUpdatedState`). "
                "4. Evitar leituras de `State` no escopo de composables pais desnecessariamente."
            ),
        })

    if coroutine_hits > 30:
        issues.append({
            "severity": "warning",
            "category": "cpu",
            "title": f"Alta Frequência de Resumption de Coroutines ({coroutine_hits} amostras)",
            "detail": (
                f"`BaseContinuationImpl.resumeWith` aparece em {coroutine_hits} amostras. "
                f"Muitas coroutines sendo suspensas e retomadas por frame."
            ),
            "action": (
                "Verificar se coroutines em loops ou `LaunchedEffect` estão sendo lançadas "
                "desnecessariamente a cada recomposição. Usar `rememberCoroutineScope()` "
                "e cancelar jobs anteriores antes de relançar."
            ),
        })

    return {
        "issues": issues,
        "insights": insights,
        "summary": {
            "total_cpu_seconds": round(total_cpu_time, 2),
            "total_context_switches": total_switches,
            "top_processes": sched[:10],
            "top_callstacks": samples[:10],
            "jvm_callstacks": jvm[:20],
            "app_callstacks": cpu_data.get("app_callstacks", []),
            "cpu_frequencies": valid_freqs,
        },
    }


def analyze_frames(frames_data):
    issues = []
    insights = []

    total = frames_data.get("total_frames", 0)
    dropped = frames_data.get("dropped_frames", 0)
    dropped_pct = frames_data.get("dropped_pct", 0)
    percentiles = frames_data.get("frame_duration_percentiles_ms", {})
    jank_causes = frames_data.get("jank_causes", {})

    if total == 0:
        insights.append("Nenhum dado de frame encontrado no trace. O app pode não ter renderizado nada durante a coleta.")
        return {"issues": issues, "insights": insights, "summary": frames_data}

    insights.append(f"Total de frames analisados: {total}")

    # Dropped frames
    if dropped_pct >= THRESHOLDS["dropped_pct_critical"]:
        issues.append({
            "severity": "critical",
            "category": "frames",
            "title": f"Jank Crítico: {dropped_pct:.1f}% de Frames Dropados",
            "detail": f"{dropped} de {total} frames não foram entregues no tempo ({dropped_pct:.1f}%). "
                      f"Usuário percebe stuttering evidente.",
            "action": "Usar Perfetto UI para identificar qual fase (CPU, GPU, input) causa os drops. "
                      "Verificar operações síncronas na UI thread.",
        })
    elif dropped_pct >= THRESHOLDS["dropped_pct_warn"]:
        issues.append({
            "severity": "warning",
            "category": "frames",
            "title": f"Frames Dropados: {dropped_pct:.1f}%",
            "detail": f"{dropped} frames dropados de {total} total.",
            "action": "Investigar picos de CPU/GPU que coincidam com os drops no timeline.",
        })

    # Latência de frames
    p95 = percentiles.get("p95", 0)
    p99 = percentiles.get("p99", 0)

    if p95 > THRESHOLDS["frame_p99_ms"]:
        issues.append({
            "severity": "critical",
            "category": "frames",
            "title": f"Alta Latência de Frame (P95 = {p95:.1f}ms)",
            "detail": f"95% dos frames levam mais de {p95:.1f}ms para renderizar (threshold: 16.67ms). "
                      f"P99 = {p99:.1f}ms.",
            "action": "Otimizar composição de layout (remover layers desnecessárias, usar hardware layers). "
                      "Verificar animações e overdraw.",
        })
    elif p95 > THRESHOLDS["frame_p95_ms"]:
        issues.append({
            "severity": "warning",
            "category": "frames",
            "title": f"Latência de Frame Elevada (P95 = {p95:.1f}ms)",
            "detail": f"Frames no P95 excedem o budget de 16.67ms.",
            "action": "Verificar render passes, bitmaps grandes e complexity de shaders.",
        })

    # Causas de jank
    if jank_causes:
        top_cause = max(jank_causes, key=jank_causes.get)
        insights.append(f"Causa principal de jank: {top_cause} ({jank_causes[top_cause]} ocorrências)")

    return {
        "issues": issues,
        "insights": insights,
        "summary": {
            "total_frames": total,
            "dropped_frames": dropped,
            "dropped_pct": dropped_pct,
            "frame_percentiles_ms": percentiles,
            "jank_causes": jank_causes,
            "jank_jvm_callstacks": frames_data.get("jank_jvm_callstacks", []),
            "jank_app_callstacks": frames_data.get("jank_app_callstacks", []),
        },
    }


def analyze_battery(battery_data, duration_seconds):
    issues = []
    insights = []
    counters = battery_data.get("battery_counters", [])
    power_rails = battery_data.get("power_rails", [])

    # Charge drenada em microampere-horas
    charge_counter = next((c for c in counters if c.get("counter_name") == "batt_charge_uah"), None)
    if charge_counter:
        delta_uah = abs(charge_counter.get("delta", 0))
        delta_mc = delta_uah * 3.6  # uAh → mC (milliCoulombs)
        if delta_mc > 0:
            insights.append(f"Carga drenada: {delta_mc:.1f} mC em {duration_seconds:.0f}s")
            drain_rate = delta_mc / duration_seconds if duration_seconds else 0
            insights.append(f"Taxa de drain: {drain_rate:.2f} mC/s")
            if drain_rate > 5.0:
                issues.append({
                    "severity": "warning",
                    "category": "battery",
                    "title": "Alto Consumo de Bateria",
                    "detail": f"Taxa de drain de {drain_rate:.2f} mC/s durante o trace. "
                              f"Pode resultar em bateria drenando em horas.",
                    "action": "Verificar wake locks, sync periódico, GPS, e jobs em background.",
                })

    # Power rails
    if power_rails:
        top_rail = power_rails[0]
        insights.append(f"Maior consumidor de energia: {top_rail.get('rail_name', 'N/A')} "
                        f"({top_rail.get('total_mw', 0):.1f} mW)")

    return {
        "issues": issues,
        "insights": insights,
        "summary": {
            "battery_counters": counters,
            "power_rails": power_rails[:5],
        },
    }


def build_recommendations(all_issues):
    """Gera recomendações consolidadas ordenadas por severidade."""
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_issues = sorted(all_issues, key=lambda x: severity_order.get(x["severity"], 99))
    return [
        {
            "priority": i + 1,
            "severity": issue["severity"],
            "title": issue["title"],
            "detail": issue["detail"],
            "action": issue["action"],
            "category": issue["category"],
        }
        for i, issue in enumerate(sorted_issues)
    ]


def main():
    parser = argparse.ArgumentParser(description="Analisa métricas do trace Perfetto")
    parser.add_argument("--input", default="/tmp/perfetto_parsed.json", help="JSON parseado")
    parser.add_argument("--output", default="/tmp/perfetto_insights.json", help="JSON de insights")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERRO: Arquivo não encontrado: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input) as f:
        data = json.load(f)

    duration = data.get("trace_duration_seconds", 0)

    print("Analisando memória...")
    mem_analysis = analyze_memory(data.get("memory", {}))

    print("Analisando CPU...")
    cpu_analysis = analyze_cpu(data.get("cpu", {}))

    print("Analisando frames...")
    frame_analysis = analyze_frames(data.get("frames", {}))

    print("Analisando battery...")
    battery_analysis = analyze_battery(data.get("battery", {}), duration)

    all_issues = (
        mem_analysis["issues"]
        + cpu_analysis["issues"]
        + frame_analysis["issues"]
        + battery_analysis["issues"]
    )

    all_insights = (
        mem_analysis["insights"]
        + cpu_analysis["insights"]
        + frame_analysis["insights"]
        + battery_analysis["insights"]
    )

    recommendations = build_recommendations(all_issues)

    output = {
        "trace_duration_seconds": duration,
        "recommendations": recommendations,
        "insights": all_insights,
        "memory": mem_analysis["summary"],
        "cpu": cpu_analysis["summary"],
        "frames": frame_analysis["summary"],
        "battery": battery_analysis["summary"],
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)

    critical = sum(1 for r in recommendations if r["severity"] == "critical")
    warnings = sum(1 for r in recommendations if r["severity"] == "warning")
    print(f"\nAnálise concluída: {critical} críticos, {warnings} avisos → {args.output}")


if __name__ == "__main__":
    main()
