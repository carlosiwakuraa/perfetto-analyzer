#!/usr/bin/env python3
"""Gera relatório markdown a partir dos insights do Perfetto."""

import argparse
import json
import sys
import os
import subprocess
from datetime import datetime


def _demangle(name):
    """Tenta demangling de símbolos C++. Retorna o nome original em caso de falha."""
    if not name.startswith("_Z"):
        return name
    try:
        result = subprocess.run(
            ["c++filt", name], capture_output=True, text=True, timeout=2
        )
        demangled = result.stdout.strip()
        return demangled if demangled else name
    except Exception:
        return name


def _shorten_jvm_name(name):
    """Encurta nomes JVM mantendo classe + método legíveis.

    'androidx.compose.runtime.Recomposer$runRecomposeAndApplyChanges$2$1.invoke'
    → 'compose.runtime.Recomposer · runRecomposeAndApplyChanges'
    """
    # Separar a parte do método (após o último ponto que não é lambda)
    parts = name.split(".")
    if len(parts) >= 2:
        method = parts[-1]
        class_part = ".".join(parts[:-1])
    else:
        return name[:80]

    # Remover sufixos de lambda ($1, $2, etc.) da classe
    class_clean = class_part.split("$")[0]

    # Extrair apenas o nome da classe (sem prefixo de pacote), mas manter 1-2 segmentos de contexto
    class_segments = class_clean.split(".")
    if len(class_segments) > 3:
        class_display = ".".join(class_segments[-3:])
    else:
        class_display = class_clean

    # Pegar o nome do método antes de qualquer $ (lambda suffix)
    method_clean = method.split("$")[0]
    # Remover sufixos gerados pelo Kotlin (ex: -eZhPAX0$ui_release)
    method_clean = method_clean.split("-")[0]

    result = f"{class_display} · {method_clean}"
    return result[:90] if len(result) > 90 else result


def format_bytes(b):
    if b is None:
        return "N/A"
    if b >= 1024 * 1024:
        return f"{b / 1024 / 1024:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def format_pct(v):
    return f"{v:.1f}%" if v is not None else "N/A"


def severity_emoji(s):
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(s, "⚪")


JVM_NOISE = {"RuntimeInit", "ZygoteInit", "NativeStart", "Looper.loop"}


def _correlations(trace_type, recommendations):
    """Sugere traces complementares com base no tipo atual e nos problemas encontrados."""
    if trace_type == "all":
        return []

    categories = {r.get("category") for r in recommendations}
    titles = " ".join(r.get("title", "") for r in recommendations)
    suggestions = []

    if trace_type == "cpu":
        if "Recomposição" in titles or "Compose" in titles:
            suggestions.append((
                "frames",
                "Correlacionar recomposições com drops reais — o trace de frames mostra se as "
                "recomposições detectadas aqui estão de fato causando frames janked visíveis.",
            ))
        if "cpu" in categories:
            suggestions.append((
                "memory",
                "Verificar se heap churn está pressionando a CPU — GC frequente aparece como "
                "picos de CPU; o trace de memória confirma alocações excessivas nos mesmos hot paths.",
            ))

    elif trace_type == "frames":
        if "frames" in categories:
            suggestions.append((
                "cpu",
                "Identificar a callstack responsável pelos drops — o trace de CPU a 60 Hz mostra "
                "exatamente qual função estava rodando durante cada deadline miss.",
            ))

    elif trace_type == "memory":
        if "memory" in categories:
            suggestions.append((
                "cpu",
                "Localizar os hotspots de alocação no callstack — o trace de CPU revela quais "
                "funções disparam as alocações identificadas aqui.",
            ))
            suggestions.append((
                "frames",
                "Verificar se o churn de memória/GC está causando jank — pausas de GC aparecem "
                "como frames dropados no trace de frames.",
            ))

    elif trace_type == "battery":
        suggestions.append((
            "cpu",
            "Identificar quais funções consomem mais CPU e drenam a bateria — o trace de CPU "
            "mapeia o gasto energético a callstacks específicos.",
        ))
        if recommendations:
            suggestions.append((
                "all",
                "Trace completo para correlação total — combina CPU, frames e memória para uma "
                "visão unificada do drain.",
            ))

    return suggestions


def generate_report(data, package, trace_type):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    duration = data.get("trace_duration_seconds", 0)
    recommendations = data.get("recommendations", [])
    insights = data.get("insights", [])
    memory = data.get("memory", {})
    cpu = data.get("cpu", {})
    frames = data.get("frames", {})
    battery = data.get("battery", {})

    lines = []

    # Cabeçalho
    lines += [
        f"# Relatório de Performance — `{package}`",
        f"",
        f"**Data:** {now}  |  **Duração:** {duration:.0f}s  |  **Tipo de trace:** `{trace_type}`",
        f"",
    ]

    # Resumo Executivo
    lines += ["## Resumo Executivo", ""]
    if recommendations:
        for rec in recommendations[:5]:
            emoji = severity_emoji(rec["severity"])
            lines.append(f"{emoji} **{rec['title']}** — {rec['detail'][:120]}...")
    else:
        lines.append("Nenhum problema crítico detectado neste trace.")
    lines.append("")

    if insights:
        lines += ["**Observações:**", ""]
        for insight in insights[:6]:
            lines.append(f"- {insight}")
        lines.append("")

    # Memória
    lines += ["---", "", "## Memória", ""]

    unreleased_mb = memory.get("total_unreleased_mb", 0)
    allocated_mb = memory.get("total_allocated_mb", 0)
    art_mb = memory.get("total_art_retained_mb", 0)

    lines += [
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Heap nativo não-liberado | {unreleased_mb:.1f} MB |",
        f"| Total alocado (nativo) | {allocated_mb:.1f} MB |",
        f"| Objetos Java/Kotlin retidos (ART) | {art_mb:.1f} MB |",
        f"",
    ]

    native_allocs = memory.get("top_native_allocators", [])
    if native_allocs:
        lines += ["### Top Alocadores de Heap Nativo", ""]
        lines += ["| # | Função (topo do stack) | Bytes Não-liberados | Total Alocado |"]
        lines += ["|---|---|---|---|"]
        for i, alloc in enumerate(native_allocs[:10]):
            fn = alloc.get("stack", ["?"])[0] if alloc.get("stack") else "desconhecida"
            fn = fn[:60] if len(fn) > 60 else fn
            unreleased = format_bytes(alloc.get("unreleased_bytes", 0))
            total = format_bytes(alloc.get("total_bytes", 0))
            lines.append(f"| {i+1} | `{fn}` | {unreleased} | {total} |")
        lines.append("")

    art_objects = memory.get("top_art_objects", [])
    if art_objects:
        lines += ["### Top Objetos Java/Kotlin Retidos (ART)", ""]
        lines += ["| Classe | Instâncias | Tamanho Total |"]
        lines += ["|---|---|---|"]
        for obj in art_objects[:10]:
            name = str(obj.get("type_name", "?"))[:70]
            count = obj.get("instance_count", 0)
            size = format_bytes(obj.get("total_size", 0))
            lines.append(f"| `{name}` | {count:,} | {size} |")
        lines.append("")

    # CPU
    lines += ["---", "", "## CPU", ""]

    total_cpu = cpu.get("total_cpu_seconds", 0)
    ctx_switches = cpu.get("total_context_switches", 0)

    lines += [
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Tempo total de CPU (todos os processos) | {total_cpu:.2f}s |",
        f"| Total de context switches | {ctx_switches:,} |",
        f"",
    ]

    top_procs = cpu.get("top_processes", [])
    if top_procs:
        lines += ["### Processos por Tempo de CPU", ""]
        lines += ["| Processo | Tempo CPU (s) | Context Switches |"]
        lines += ["|---|---|---|"]
        for proc in top_procs[:10]:
            name = (proc.get("process_name") or "?")[:50]
            t = proc.get("total_cpu_seconds", 0)
            sw = proc.get("context_switches", 0)
            lines.append(f"| `{name}` | {t:.3f}s | {sw:,} |")
        lines.append("")

    # Frames JVM (Kotlin/Java) — ofensores reais na cadeia de chamada
    jvm_callstacks = [
        j for j in cpu.get("jvm_callstacks", [])
        if not any(noise in j.get("function_name", "") for noise in JVM_NOISE)
    ]
    if jvm_callstacks:
        total_jvm = max(j.get("sample_count", 0) for j in jvm_callstacks) if jvm_callstacks else 1
        lines += ["### Top Ofensores — Classes Kotlin/Java", ""]
        lines += ["> `Amostras` = quantas coletas de CPU tinham esta classe ativa na pilha de chamadas.", ""]
        lines += ["| Classe / Método | Amostras | % |"]
        lines += ["|---|---|---|"]
        for j in jvm_callstacks[:20]:
            fn = j.get("function_name", "?")
            count = j.get("sample_count", 0)
            pct = count / total_jvm * 100 if total_jvm else 0
            # Encurtar nomes longos mantendo a parte mais informativa
            short = _shorten_jvm_name(fn)
            lines.append(f"| `{short}` | {count} | {pct:.0f}% |")
        lines.append("")

    # Frames do código do app (o que o DEV pode agir)
    app_callstacks = cpu.get("app_callstacks", [])
    if app_callstacks:
        lines += ["### Código do App — Hotspots", ""]
        lines += ["> Funções do seu código que estavam ativas no momento das amostras de CPU.", ""]
        lines += ["| Classe / Método | Thread | Amostras |"]
        lines += ["|---|---|---|"]
        for cs in app_callstacks[:20]:
            fn = _shorten_jvm_name(cs.get("function_name", "?"))
            thread = (cs.get("thread_name") or "?")[:25]
            count = cs.get("sample_count", 0)
            lines.append(f"| `{fn}` | `{thread}` | {count} |")
        lines.append("")

    # Top frames nativos (contexto de baixo nível)
    callstacks = cpu.get("top_callstacks", [])
    if callstacks:
        total_samples = sum(cs.get("sample_count", 0) for cs in callstacks)
        lines += ["### Top Frames Nativos (contexto de baixo nível)", ""]
        lines += ["| Função | Thread | Amostras |"]
        lines += ["|---|---|---|"]
        for cs in callstacks[:10]:
            fn = cs.get("function_name", "?")
            fn = _demangle(fn)
            fn = fn[:60] if len(fn) > 60 else fn
            thread = (cs.get("thread_name") or "?")[:25]
            count = cs.get("sample_count", 0)
            lines.append(f"| `{fn}` | `{thread}` | {count} |")
        lines.append("")

    cpu_freqs = cpu.get("cpu_frequencies", [])
    if cpu_freqs:
        lines += ["### Frequência de CPU por Core", ""]
        lines += ["| CPU | Frequência Média (MHz) | Frequência Máxima (MHz) |"]
        lines += ["|---|---|---|"]
        for f in cpu_freqs:
            lines.append(f"| CPU {f.get('cpu', '?')} | {f.get('avg_freq_mhz', 0):.0f} | {f.get('max_freq_mhz', 0):.0f} |")
        lines.append("")

    # Frames
    lines += ["---", "", "## Frames", ""]

    total_frames = frames.get("total_frames", 0)
    dropped_frames = frames.get("dropped_frames", 0)
    dropped_pct = frames.get("dropped_pct", 0)
    pcts = frames.get("frame_percentiles_ms", {})
    jank_causes = frames.get("jank_causes", {})

    if total_frames > 0:
        # Indicador visual de qualidade
        if dropped_pct < 1.0:
            quality = "🟢 Boa"
        elif dropped_pct < 5.0:
            quality = "🟡 Aceitável"
        else:
            quality = "🔴 Ruim"

        lines += [
            f"| Métrica | Valor | Threshold |",
            f"|---|---|---|",
            f"| Qualidade geral | {quality} | — |",
            f"| Total de frames | {total_frames:,} | — |",
            f"| Frames dropados | {dropped_frames:,} ({format_pct(dropped_pct)}) | < 1% |",
            f"| Frame P50 | {pcts.get('p50', 0):.1f}ms | < 8ms |",
            f"| Frame P95 | {pcts.get('p95', 0):.1f}ms | < 16.67ms |",
            f"| Frame P99 | {pcts.get('p99', 0):.1f}ms | < 32ms |",
            f"| Frame máximo | {pcts.get('max', 0):.1f}ms | — |",
            f"",
        ]

        if jank_causes:
            lines += ["### Causas de Jank", ""]
            lines += ["| Causa | Ocorrências |"]
            lines += ["|---|---|"]
            for cause, count in sorted(jank_causes.items(), key=lambda x: -x[1]):
                lines.append(f"| {cause} | {count:,} |")
            lines.append("")

        jank_jvm = frames.get("jank_jvm_callstacks", [])
        if jank_jvm:
            jank_jvm_filtered = [
                j for j in jank_jvm
                if not any(n in j.get("function_name", "") for n in JVM_NOISE)
            ]
            if jank_jvm_filtered:
                lines += ["### APIs Android ativas durante Frames Janked", ""]
                lines += ["> CPU samples capturados **dentro da janela** de frames que perderam o deadline.", ""]
                lines += ["| Classe / Método | Amostras |"]
                lines += ["|---|---|"]
                for j in jank_jvm_filtered[:15]:
                    short = _shorten_jvm_name(j.get("function_name", "?"))
                    lines.append(f"| `{short}` | {j.get('sample_count', 0)} |")
                lines.append("")

        jank_app = frames.get("jank_app_callstacks", [])
        if jank_app:
            lines += ["### Código do App durante Frames Janked", ""]
            lines += ["> Funções do **seu código** que estavam ativas quando o frame atrasou.", ""]
            lines += ["| Classe / Método | Thread | Amostras |"]
            lines += ["|---|---|---|"]
            for j in jank_app[:15]:
                short = _shorten_jvm_name(j.get("function_name", "?"))
                thread = (j.get("thread_name") or "?")[:25]
                lines.append(f"| `{short}` | `{thread}` | {j.get('sample_count', 0)} |")
            lines.append("")
    else:
        lines += ["> Nenhum dado de frame disponível neste trace.", ""]

    # Battery
    lines += ["---", "", "## Battery", ""]

    battery_counters = battery.get("battery_counters", [])
    power_rails = battery.get("power_rails", [])

    charge = next((c for c in battery_counters if c.get("counter_name") == "batt_charge_uah"), None)
    if charge:
        delta_uah = abs(charge.get("delta", 0))
        delta_mc = delta_uah * 3.6
        drain_rate = delta_mc / duration if duration else 0

        lines += [
            f"| Métrica | Valor |",
            f"|---|---|",
            f"| Carga drenada | {delta_mc:.1f} mC ({delta_uah:.1f} µAh) |",
            f"| Taxa de drain | {drain_rate:.2f} mC/s |",
            f"| Duração do trace | {duration:.0f}s |",
            f"",
        ]
    else:
        lines += ["> Dados de bateria não disponíveis neste trace.", ""]

    if power_rails:
        lines += ["### Power Rails", ""]
        lines += ["| Rail | Consumo Total (mW) |"]
        lines += ["|---|---|"]
        for rail in power_rails:
            lines.append(f"| `{rail.get('rail_name', '?')}` | {rail.get('total_mw', 0):.1f} |")
        lines.append("")

    # Recomendações
    lines += ["---", "", "## Recomendações", ""]

    if recommendations:
        for rec in recommendations:
            emoji = severity_emoji(rec["severity"])
            lines += [
                f"### {rec['priority']}. {emoji} {rec['title']}",
                f"",
                f"**Problema:** {rec['detail']}",
                f"",
                f"**Ação:** {rec['action']}",
                f"",
            ]
    else:
        lines += ["Nenhum problema detectado automaticamente. Revise o trace manualmente no [Perfetto UI](https://perfetto.dev/ui).", ""]

    # Próximos Passos
    correlations = _correlations(trace_type, recommendations)

    next_steps = ["---", "", "## Próximos Passos", ""]

    if correlations:
        for next_type, reason in correlations:
            next_steps.append(f"- [ ] **Trace `{next_type}`** — {reason}")
        next_steps.append("")

    next_steps += [
        "- [ ] Abrir o arquivo `.pb` em [perfetto.dev/ui](https://perfetto.dev/ui) para análise visual",
        "- [ ] Usar o SQL Explorer do Perfetto UI para queries customizadas",
        "- [ ] Correlacionar picos de CPU/memória com interações do usuário na timeline",
        "- [ ] Comparar este trace com um baseline (versão anterior do app) para medir regressões",
        "",
        "---",
        "",
        f"*Gerado por perfetto-analyzer em {now}*",
    ]

    lines += next_steps

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Gera relatório markdown de análise Perfetto")
    parser.add_argument("--insights", default="/tmp/perfetto_insights.json", help="JSON de insights")
    parser.add_argument("--package", default="unknown", help="Package do app")
    parser.add_argument("--trace-type", default="all", help="Tipo de trace")
    args = parser.parse_args()

    if not os.path.exists(args.insights):
        print(f"ERRO: Arquivo não encontrado: {args.insights}", file=sys.stderr)
        sys.exit(1)

    with open(args.insights) as f:
        data = json.load(f)

    report = generate_report(data, args.package, args.trace_type)
    print(report)


if __name__ == "__main__":
    main()
