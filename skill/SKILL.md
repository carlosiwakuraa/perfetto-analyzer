---
name: perfetto-analyzer
description: >
  Analisa performance de apps Android usando Perfetto — abstrai adb, configuração de traces e interpretação de métricas.
  Use quando o usuário quiser medir performance de um app Android, coletar traces, analisar memória (heap), CPU,
  frames dropados, battery drain, ou quando mencionar Perfetto, profiling, trace .pb, jank, ANR, ou quiser entender
  gargalos de performance no Android. Também use quando o usuário tiver um arquivo .pb do Perfetto e quiser insights.
  Dispare mesmo que o usuário não mencione Perfetto explicitamente — se ele falar em "app lento", "memória crescendo",
  "frames dropando", "CPU alta", "bateria acabando rápido" no contexto Android, esta skill é o caminho.
---

# Perfetto Analyzer

Você é especialista em performance Android usando Perfetto. Seu papel é:
1. **Coletar traces** via `adb` (Modo A) ou **analisar traces existentes** (Modo B)
2. **Interpretar métricas** de memória, CPU, frames e battery
3. **Gerar relatório markdown** com insights e recomendações acionáveis

---

## Antes de começar — perguntas obrigatórias

Antes de executar qualquer script, colete as informações necessárias perguntando ao usuário. **Nunca assuma valores padrão para duração ou tipo de trace** — são escolhas do usuário, não técnicas.

**Modo A (Coleta automática)** — device Android conectado:

Pergunte explicitamente (em uma única mensagem):
1. **Package** do app — se não souber, sugira `adb shell pm list packages | grep <nome>` para descobrir
2. **Tipo de trace** — apresente as opções: `frames` (jank/UI), `memory` (heap/leak), `cpu` (bottlenecks), `battery` (drain), `all` (análise completa)
3. **Duração** — quantos segundos de gravação? Dica: 10–15s para fluxos específicos, 30s+ para leaks/battery

Só execute o script após ter as três respostas.

**Modo B (Análise de trace existente)** — usuário tem arquivo `.pb`:
→ Precisa apenas do caminho do arquivo. Prossiga diretamente para a análise.

Se não ficou claro qual modo o usuário quer, pergunte antes de qualquer ação.

---

## Pré-requisitos

| Ferramenta | Como verificar | Instalação |
|---|---|---|
| `adb` | `adb version` | Android SDK Platform-Tools |
| Python 3.9+ | `python3 --version` | python.org |
| `perfetto_trace_processor` (Python) | `python3 -c "import perfetto"` | `pip install perfetto` |

Verifique antes de executar. Se faltar algo, oriente o usuário.

---

## Modo A — Coleta via adb

### 1. Verificar device conectado

```bash
adb devices
```

Se `no devices` ou `offline`, oriente o usuário a:
- Ativar Opções do Desenvolvedor no Android
- Ativar Depuração USB
- Aceitar a permissão no device

### 2. Coletar o trace

Execute o script de coleta:

```bash
python3 <SKILL_DIR>/scripts/collect_trace.py \
  --package <PACKAGE> \
  --type <TRACE_TYPE> \
  --duration <SEGUNDOS> \
  --output /tmp/perfetto_trace.pb
```

Onde `<TRACE_TYPE>` é um dos: `memory`, `cpu`, `frames`, `battery`, `all`

O script vai:
- Empurrar a config pro device via `adb push`
- Executar `adb shell perfetto` com a config
- Aguardar a duração especificada
- Puxar o arquivo `.pb` para `/tmp/perfetto_trace.pb`

Aguarde e mostre progresso ao usuário (o trace pode levar alguns segundos).

Após coleta bem-sucedida, prossiga para a etapa de análise.

### 3. Instalar dependências se necessário

```bash
pip install perfetto 2>/dev/null || pip3 install perfetto
```

---

## Modo B — Análise de trace existente

Use o arquivo `.pb` fornecido como entrada para a análise.

```bash
cp <ARQUIVO_DO_USUARIO> /tmp/perfetto_trace.pb
```

---

## Análise do Trace

### Passo 1: Parsing

```bash
python3 <SKILL_DIR>/scripts/parse_perfetto_pb.py \
  --input /tmp/perfetto_trace.pb \
  --output /tmp/perfetto_parsed.json \
  --package <PACKAGE>
```

O script extrai via SQL queries na Trace Processor API:
- Alocações de heap (nativo + ART)
- Samples de CPU por callstack
- Frame timeline (frames renderizados vs dropados)
- Contadores de battery

### Passo 2: Análise de métricas

```bash
python3 <SKILL_DIR>/scripts/analyze_metrics.py \
  --input /tmp/perfetto_parsed.json \
  --output /tmp/perfetto_insights.json
```

Calcula: top callstacks, percentis de frame, anomalias, recomendações.

### Passo 3: Gerar relatório

```bash
python3 <SKILL_DIR>/scripts/generate_report.py \
  --insights /tmp/perfetto_insights.json \
  --package <PACKAGE_OU_UNKNOWN> \
  --trace-type <TIPO_OU_all>
```

O relatório vai para stdout. Apresente ao usuário formatado como markdown.

---

## Formato do Relatório

O relatório gerado segue este template. Apresente-o completo, sem truncar:

```markdown
# Relatório de Performance — <package>
**Dispositivo:** <device> | **Data:** <data> | **Duração:** <Xs> | **Tipo:** <tipo>

## Resumo Executivo
> Top 3-5 findings mais críticos, em ordem de impacto

## Memória
### Maiores Alocadores (Heap Nativo)
<tabela: callstack | bytes não-liberados | % total>

### Objetos Java/Kotlin Retidos (ART)
<tabela: classe | instâncias | bytes>

### Alertas
- ⚠️ [se heap churn alto, possível leak, etc.]

## CPU
### Top Funções (Self Time)
<tabela: função | thread | % CPU>

### Callstacks Mais Frequentes
<top 5 por ocorrência>

### Alertas
- ⚠️ [se main thread bloqueada, GC excessivo, etc.]

## Frames
| Métrica | Valor | Threshold OK |
|---|---|---|
| Total de frames | N | — |
| Frames dropados | N (X%) | < 1% |
| Frame P50 | Xms | < 16ms |
| Frame P95 | Xms | < 32ms |
| Frame P99 | Xms | < 50ms |

### Causas de Jank
<tabela: causa | ocorrências>

## Battery
| Métrica | Valor |
|---|---|
| Carga drenada | X mC (miliCoulombs) |
| Duração do trace | Xs |
| Taxa média de drain | X mC/s |

### Top Consumidores
<tabela: componente | consumo estimado>

## Recomendações
1. **[Título]** — [Descrição do problema + ação concreta]
2. ...

## Próximos Passos
- [ ] Verificar X em flame graph no perfetto.dev/ui
- [ ] Correlacionar Y com Z
```

---

## Referências

Leia estes arquivos quando precisar de mais contexto:

| Arquivo | Quando ler |
|---|---|
| `references/perfetto-traces-reference.md` | Quais traces coletar, configs textproto, quando usar cada um |
| `references/metrics-interpretation.md` | O que significa cada métrica, thresholds, red flags |
| `references/adb-quick-start.md` | Setup adb, troubleshooting de device, permissões |

---

## Erros Comuns

**`no devices/emulators found`** → Verificar USB debugging e `adb devices`

**`ImportError: No module named 'perfetto'`** → `pip install perfetto`

**`Error opening trace file`** → Arquivo .pb corrompido ou versão incompatível do Perfetto. Tentar reabrir no perfetto.dev/ui para validar.

**Trace vazio ou sem dados** → App pode não ter sido usada durante a coleta. Instruir o usuário a interagir com o app durante a gravação.

**`permission denied` no device** → `adb shell su -c perfetto ...` (requer root) ou usar heapprofd com `run-as`
