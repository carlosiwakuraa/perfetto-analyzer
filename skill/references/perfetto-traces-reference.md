# Referência: Tipos de Traces Perfetto

## Quando usar cada tipo

| Tipo | Use quando... | Dados coletados |
|---|---|---|
| `memory` | App consome muita RAM, cresce ao longo do tempo, crashes por OOM | Heap nativo (heapprofd), ART heap dumps, contadores de memória |
| `cpu` | App trava, UI não responde, ANR, processamento lento | CPU sampling, scheduling, frequência de cores |
| `frames` | Animações travando, scroll não fluido, UI parecendo "lenta" | Frame timeline, jank classification, vsync events |
| `battery` | Bateria acabando rápido, app continua drenando em background | Battery counters, power rails, wake locks |
| `all` | Não sabe onde está o problema, análise geral inicial | Tudo acima combinado (buffer maior, mais pesado) |

---

## Configs textproto (resumo)

Cada arquivo em `scripts/configs/` usa os seguintes `data_sources`:

### memory.textproto
```
android.heapprofd         → Native heap (C/C++ malloc/free)
android.java_hprof        → ART heap dump (Java/Kotlin objects)
linux.sys_stats           → meminfo counters
linux.ftrace              → mm_event, lowmemorykiller
```

### cpu.textproto
```
linux.perf                → CPU sampling (perf_event_config)
linux.ftrace              → sched_switch, sched_wakeup, cpu_frequency
linux.sys_stats           → stat_cpu_times, cpufreq
linux.process_stats       → lista de processos/threads
```

### frames.textproto
```
android.surfaceflinger.frametimeline  → Frame timeline (Android 12+)
android.atrace            → gfx, view, wm, am, input categories
linux.ftrace              → sched_switch, drm_vblank, gpu_mem
```

### battery.textproto
```
android.power             → battery_counters + power rails
linux.ftrace              → wakeup_source_activate/deactivate, suspend_resume
linux.sys_stats           → cpu_times para correlação
```

### all.textproto
Combina todos acima. Usa buffer de 128 MB.

---

## Limitações por API Level

| Feature | API Level mínimo |
|---|---|
| heapprofd (native heap) | API 26 (Android 8.0) |
| ART heap dumps | API 28 (Android 9.0) |
| Frame Timeline completo | API 31 (Android 12) |
| Power rails | Depende do hardware (Qualcomm/Tensor) |
| Perfetto daemon nativo | API 29 (Android 10) |

**Para Android < 10:** Use `adb shell tracebox` ou o binário Perfetto estático do AOSP.

---

## Duração recomendada por caso de uso

| Cenário | Duração |
|---|---|
| Startup do app | 5–10s |
| Fluxo de navegação específico | 10–20s |
| Scroll / animação | 5–15s |
| Análise de memory leak | 30–60s (interagir muito com o app) |
| Análise de battery | 60–120s |
| Análise completa (all) | 30–60s |

---

## Coleta manual via adb (referência)

```bash
# Listar devices
adb devices

# Push config pro device
adb push config.textproto /data/local/tmp/perfetto_config.textproto

# Iniciar trace (30 segundos)
adb shell perfetto \
  --config /data/local/tmp/perfetto_config.textproto \
  --out /data/local/tmp/trace.pb \
  --time 30s

# Aguardar e baixar
adb pull /data/local/tmp/trace.pb ./trace.pb

# Limpar device
adb shell rm /data/local/tmp/trace.pb /data/local/tmp/perfetto_config.textproto
```

---

## Visualização no Perfetto UI

Para abrir o trace coletado no browser:
1. Acesse [perfetto.dev/ui](https://perfetto.dev/ui)
2. Clique em "Open trace file"
3. Selecione o arquivo `.pb`

O Perfetto UI oferece:
- Timeline com todos os eventos
- Flamegraph de heap/CPU (selecione região no timeline)
- SQL Explorer para queries customizadas
- Comparação entre múltiplos traces
