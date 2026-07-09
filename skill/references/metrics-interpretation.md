# Interpretação de Métricas do Perfetto

## Memória

### Heap Nativo (heapprofd)

| Métrica | O que significa | Red Flag |
|---|---|---|
| `unreleased_bytes` | Bytes alocados que ainda não foram liberados | > 50 MB acumulado sugere leak |
| `total_bytes` | Total bruto alocado (inclui o que foi liberado depois) | — |
| `alloc_count` | Número de chamadas `malloc()` | — |
| Churn ratio | `total / unreleased` | > 10x sugere muitas alocações temporárias |

**Modos de visualização:**
- **Unreleased malloc size** (padrão): foca em memória que *ainda está* alocada → detecta leaks
- **Total malloc size**: inclui memória liberada → detecta heap churn / GC pressure
- **Unreleased malloc count**: conta alocs, ignora tamanho → útil quando leak é muitos objetos pequenos
- **Total malloc count**: total de chamadas malloc → detecta hot paths de alocação

### ART Heap Dump (Java/Kotlin)

| Métrica | O que significa | Red Flag |
|---|---|---|
| `instance_count` | Instâncias vivas de cada classe | Número inesperadamente alto de singletons |
| `total_size` | Bytes retidos por todas as instâncias | > 100 MB em heap de app médio é preocupante |
| Dominators | Objeto que retém outro na memória | Activity/Fragment aparecendo como dominator = leak |

**Nota crítica:** "A análise de heap profiling não é retroativa — só mostra alocações após o rastreamento iniciar."

---

## CPU

### CPU Sampling (perf events)

| Métrica | O que significa | Red Flag |
|---|---|---|
| `self_count` | Amostras onde a função é folha (onde o CPU estava de fato) | Alto = função gargalo real |
| `cumulative_count` | Amostras onde a função aparece em qualquer posição do stack | Alto = função chamada frequentemente por hot paths |
| Frequência de amostragem | Amostras por segundo (padrão: 100 Hz) | Frequência baixa → menos resolução |

### Scheduling

| Métrica | O que significa | Red Flag |
|---|---|---|
| `dur` | Duração que uma thread ficou no estado "running" | Thread com poucos picos longos → não multi-threaded |
| Context switches | Trocas de contexto | > 10k/s pode indicar contention |
| Main thread CPU% | % do tempo total de CPU na main thread | > 20% = operações bloqueantes na UI thread |

### Throttling e Frequência

- Se CPU estiver a < 50% da frequência máxima → thermal throttling ou battery saver
- `cpu_idle` events frequentes + `cpu_frequency` baixo = CPU economizando energia (pode ser OK)

---

## Frames

### Frame Timeline (Android 12+ / API 31+)

| Campo | Valores | Significado |
|---|---|---|
| `present_type` | `On-time Present`, `Late Present`, `Early Present` | Se foi entregue no vsync correto |
| `on_time_finish` | 0 ou 1 | 0 = frame chegou tarde → dropped |
| `jank_type` | ver abaixo | Causa do jank |

### Tipos de Jank (jank_type)

| Tipo | Causa | Solução |
|---|---|---|
| `App Deadline Missed` | App não terminou o frame a tempo | Reduzir trabalho na UI thread |
| `SurfaceFlinger CPU Deadline Missed` | SurfaceFlinger não compôs a tempo | Reduzir layers/overdraw |
| `SurfaceFlinger GPU Deadline Missed` | GPU não finalizou renderização a tempo | Otimizar shaders, reduzir complexidade visual |
| `Buffering` | App produz frames mais rápido que display consome | Normal em alguns cenários |
| `None` | Frame foi entregue normalmente | — |

### Thresholds de Latência de Frame

| Percentil | Threshold 60fps | Threshold 90fps | Threshold 120fps |
|---|---|---|---|
| P50 | ≤ 16.67ms | ≤ 11.1ms | ≤ 8.33ms |
| P95 | ≤ 33.3ms | ≤ 22.2ms | ≤ 16.67ms |
| P99 | ≤ 50ms | ≤ 33.3ms | ≤ 25ms |

**Dropped frames %:**
- < 0.1%: Excelente
- 0.1%–1%: Bom
- 1%–5%: Aceitável (usuário pode perceber em cenários específicos)
- > 5%: Ruim (jank visível)

---

## Battery

### Contadores Principais

| Contador | Unidade | Significado |
|---|---|---|
| `batt_charge_uah` | µAh (microampere-hora) | Carga total da bateria; delta = consumo |
| `batt_current_ua` | µA | Corrente instantânea; negativo = descarregando |
| `batt_capacity_pct` | % | % de carga; delta = % consumido no trace |
| `batt_voltage_uv` | µV | Tensão; queda rápida = discharge rate alto |

**Conversão:** 1 µAh = 3.6 mC (milliCoulombs)

### Power Rails (Qualcomm/Google Tensor)

Os power rails medem consumo por subsistema em mW:

| Rail | O que mede |
|---|---|
| `power.rails.cpu.big` | CPU cores de alto desempenho |
| `power.rails.cpu.little` | CPU cores de eficiência |
| `power.rails.gpu` | GPU |
| `power.rails.mem.vddq` | Memória RAM |
| `power.rails.ddr.a/b/c` | Interfaces de memória |

**Referência de consumo típico (varia por device):**
- App idle: ~5–20 mW total
- App ativo (UI, rede): ~100–300 mW
- App com vídeo/jogo: ~500–2000 mW

---

## O que olhar primeiro (checklist rápido)

1. **Frames** → % dropped + P95. Se > 1% dropped, há jank, investigue CPU/GPU timeline.
2. **CPU** → Processos com mais CPU time. Main thread alta? → operações bloqueantes.
3. **Memória** → unreleased_bytes crescendo ao longo do trace? → leak. Churn alto? → GC.
4. **Battery** → Drain rate acima do esperado? → wake locks, sync agressivo, GPS.
