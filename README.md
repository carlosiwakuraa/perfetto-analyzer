# perfetto-analyzer

> Skill de IA para análise de performance Android com [Perfetto](https://perfetto.dev) — funciona com Claude Code, Cursor, GitHub Copilot, Codex, Antigravity e Devin.

Instale uma vez. Seu assistente de IA vira um especialista em performance Android: coleta traces Perfetto via `adb`, analisa callstacks de CPU, alocações de memória, timelines de frames e contadores de bateria, e gera um relatório markdown estruturado com recomendações acionáveis.

---

## Índice

- [Agentes de IA suportados](#agentes-de-ia-suportados)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Como usar](#como-usar)
  - [Modo A — Coletar trace de um device conectado](#modo-a--coletar-trace-de-um-device-conectado)
  - [Modo B — Analisar um arquivo .pb existente](#modo-b--analisar-um-arquivo-pb-existente)
- [Tipos de trace](#tipos-de-trace)
- [Entendendo o relatório](#entendendo-o-relatório)
  - [Resumo Executivo](#resumo-executivo)
  - [Memória](#memória)
  - [CPU](#cpu)
  - [Frames](#frames)
  - [Bateria](#bateria)
  - [Recomendações](#recomendações)
- [Referência de métricas](#referência-de-métricas)
- [Solução de problemas](#solução-de-problemas)
- [Desinstalar](#desinstalar)

---

## Agentes de IA suportados

O instalador configura automaticamente a skill em todos os agentes encontrados na sua máquina:

| Agente | Diretório da skill |
|---|---|
| Claude Code | `~/.claude/skills/perfetto-analyzer/` |
| GitHub Copilot | `~/.github/copilot/skills/perfetto-analyzer/` |
| Cursor | `~/.cursor/skills/perfetto-analyzer/` |
| Antigravity | `~/.antigravity/skills/perfetto-analyzer/` |
| Codex (OpenAI) | `~/.codex/skills/perfetto-analyzer/` |
| Devin | `~/.devin/skills/perfetto-analyzer/` |

Os diretórios são criados automaticamente caso não existam.

---

## Pré-requisitos

| Ferramenta | Como verificar | Instalação |
|---|---|---|
| `adb` | `adb version` | [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) |
| Python 3.9+ | `python3 --version` | [python.org](https://python.org) |
| Lib Python do Perfetto | `python3 -c "import perfetto"` | `pip install perfetto` |

**Configuração do device:**
1. Ative as **Opções do Desenvolvedor** no Android (toque 7 vezes em "Número da versão" nas configurações)
2. Ative **Depuração USB** dentro das Opções do Desenvolvedor
3. Conecte via USB e aceite a solicitação de autorização no device
4. Verifique com `adb devices` — o device deve aparecer como `device` (não `offline` ou `unauthorized`)

---

## Instalação

### Opção 1 — npx (sem instalação prévia)

```bash
npx perfetto-analyzer install
```

### Opção 2 — instalação global

```bash
npm install -g perfetto-analyzer
```

O script `postinstall` copia os arquivos da skill automaticamente.

### Verificar instalação

Após instalar, reinicie seu assistente de IA e pergunte:

> "Analise a performance do meu app Android"

O assistente deve pedir o nome do pacote, tipo de trace e duração — isso confirma que a skill está ativa.

---

## Como usar

### Modo A — Coletar trace de um device conectado

Descreva o que quer medir em linguagem natural:

```
Analise a performance de com.meuapp.debug — quero verificar jank na tela de feed
```

```
Meu app com.exemplo.app está usando muita memória. Colete um trace de 30 segundos.
```

```
O uso de CPU está alto em com.empresa.app, colete um trace de cpu por 15 segundos
```

O assistente vai:

1. **Verificar** se o device está conectado e o adb está funcionando
2. **Checar** se o app está aberto — se não estiver, abre automaticamente via launcher
3. **Coletar** o trace Perfetto (você verá uma contagem regressiva em tempo real)
4. **Analisar** callstacks de CPU, alocações de memória, timelines de frames e contadores de bateria
5. **Gerar** um relatório markdown completo com hotspots e recomendações

> **Durante a coleta:** interaja com o app normalmente — role, navegue, acione o fluxo lento que quer analisar. O trace captura o que acontece no device em tempo real.

Se não souber o package name do app, pergunte:

```
Como descubro o package name do meu app?
```

O assistente vai sugerir:

```bash
adb shell pm list packages | grep <nome-do-app>
```

---

### Modo B — Analisar um arquivo .pb existente

Se você já tem um arquivo de trace Perfetto (`.pb`):

```
Analise este trace: ~/Downloads/meu_trace.pb
```

```
Tenho um trace perfetto em /tmp/trace.pb, consegue encontrar memory leaks?
```

Nenhuma conexão com device é necessária — o assistente analisa o arquivo diretamente.

---

## Tipos de trace

Escolha o tipo de trace conforme o que quer investigar:

| Tipo | O que captura | Indicado para |
|---|---|---|
| `frames` | Timeline de frames, causas de jank, amostras de CPU durante frames dropados | Travadas, scroll lento, jank na UI |
| `memory` | Alocações de heap nativo, retenção de objetos Java/Kotlin | Memory leaks, uso alto de heap, GC pressure |
| `cpu` | Amostragem de CPU com callstacks completos (Java, Kotlin, nativo) | Operações lentas, gargalos de CPU, funções quentes |
| `battery` | Contadores de drain da bateria, power rails | Drain rápido de bateria, wake locks, atividade em background |
| `all` | Todos os anteriores combinados | Auditoria completa de performance |

**Durações recomendadas:**
- `frames` / `cpu`: 10–15 segundos (acione a interação lenta uma vez)
- `memory`: 30–60 segundos (navegue por várias telas para acumular alocações)
- `battery`: 60–120 segundos (precisa de tempo suficiente para medir drain significativo)

---

## Entendendo o relatório

O relatório é dividido em cinco seções. Veja o que cada uma significa.

### Resumo Executivo

```
## Resumo Executivo
> 🔴 43% das amostras de CPU na main thread — operações bloqueantes detectadas na UI
> 🟡 12% de frames dropados (P95: 48ms) — jank visível para o usuário
> 🟢 Memória estável — nenhum padrão de leak detectado
```

Lista ranqueada dos problemas mais críticos, do mais ao menos impactante. Comece aqui para decidir o que corrigir primeiro.

Ícones de severidade:
- 🔴 **Crítico** — impacta diretamente a experiência do usuário, corrija imediatamente
- 🟡 **Atenção** — problema perceptível, deve ser endereçado
- 🟢 **OK** — dentro dos thresholds aceitáveis

---

### Memória

```
## Memória

### Maiores Alocadores (Heap Nativo)
| Callstack                         | Bytes não liberados | % do total |
|-----------------------------------|---------------------|------------|
| Bitmap.createBitmap (ImageLoader) | 18,4 MB             | 34%        |
| RenderScript.create               | 8,1 MB              | 15%        |

### Objetos Java/Kotlin Retidos (ART)
| Classe                    | Instâncias | Bytes   |
|---------------------------|------------|---------|
| android.graphics.Bitmap   | 847        | 42,3 MB |
| com.meuapp.cache.DataCache| 1          | 12,1 MB |

### Alertas
- ⚠️ Bytes não liberados crescendo ao longo do trace — possível memory leak no ImageLoader
```

**Conceitos-chave:**

| Termo | Significado |
|---|---|
| **Bytes não liberados** | Memória alocada e ainda não liberada — valores altos = possível leak |
| **Total de bytes** | Todas as alocações, incluindo as já liberadas — alto = muitos objetos temporários (GC pressure) |
| **Heap churn** | Razão `total / não liberado` > 10× = muitas alocações de curta duração → considere object pooling |
| **Dominators** | Objeto que mantém outro vivo na memória — Activity/Fragment como dominator = leak clássico |

**O que observar:**
- Bytes não liberados crescendo monotonicamente → memory leak
- A mesma classe aparecendo repetidamente no topo → hotspot de alocação
- `Activity` ou `Fragment` na lista de objetos retidos → problema de gerenciamento de ciclo de vida

---

### CPU

```
## CPU

### Hotspots do App — Código Kotlin/Java
| Função                                        | Thread      | Amostras |
|-----------------------------------------------|-------------|----------|
| com.meuapp.feed.FeedAdapter.onBindViewHolder  | main        | 142      |
| com.meuapp.image.ImageDecoder.decode          | AsyncTask#1 | 98       |

### APIs Android Ativas na Main Thread
| Função                                          | Amostras |
|-------------------------------------------------|----------|
| androidx.compose.runtime.Recomposer · recompose | 201      |
| android.graphics.Bitmap · createScaledBitmap    | 87       |

### Top Frames Nativos
| Função                | Thread       | Amostras |
|-----------------------|--------------|----------|
| libhwui.so!drawBitmap | RenderThread | 134      |
```

**Conceitos-chave:**

| Termo | Significado |
|---|---|
| **Amostras** | Quantas vezes a CPU foi pega executando essa função — mais amostras = mais tempo gasto |
| **Main thread** | Thread de UI do Android — trabalho pesado aqui causa jank diretamente |
| **Hotspots do app** | Seu código (filtrado pelo package name) — as funções que você pode de fato alterar |
| **APIs Android** | Funções do Android/Compose/AndroidX — indicam em que seu código está gastando tempo |
| **Frames nativos** | Código C/C++ em libs do sistema — `libhwui` = renderização, `libart` = overhead do runtime |

**O que observar:**
- Funções do seu pacote na main thread → mova o trabalho pesado para uma coroutine/thread em background
- `Bitmap.createScaledBitmap` ou decodificação de imagem na main thread → use Glide/Coil com carregamento assíncrono
- Funções de recomposição do Compose dominando → verifique recomposições desnecessárias com `@Stable` / `remember`
- Funções de GC (`art::gc::`) → reduza criação de objetos temporários, use object pools

---

### Frames

```
## Frames

| Métrica         | Valor     | Threshold OK |
|-----------------|-----------|--------------|
| Total de frames | 1.842     | —            |
| Frames dropados | 221 (12%) | < 1%         |
| Frame P50       | 14ms      | ≤ 16,67ms    |
| Frame P95       | 48ms      | ≤ 33,3ms     |
| Frame P99       | 112ms     | ≤ 50ms       |

### Causas de Jank
| Causa                              | Ocorrências |
|------------------------------------|-------------|
| App Deadline Missed                | 187         |
| SurfaceFlinger GPU Deadline Missed | 34          |
```

**Thresholds de frames dropados:**

| % Dropados | Avaliação |
|---|---|
| < 0,1% | Excelente |
| 0,1% – 1% | Bom |
| 1% – 5% | Aceitável (usuário pode perceber em cenários específicos) |
| > 5% | Ruim — jank visível |

**Thresholds de latência de frame (display 60 Hz):**

| Percentil | OK | Atenção | Crítico |
|---|---|---|---|
| P50 | ≤ 16,67ms | 16–33ms | > 33ms |
| P95 | ≤ 33,3ms | 33–50ms | > 50ms |
| P99 | ≤ 50ms | 50–100ms | > 100ms |

**Causas de jank explicadas:**

| Causa | Origem | Correção |
|---|---|---|
| `App Deadline Missed` | Seu app não terminou o frame a tempo | Reduza trabalho na UI thread, use `LaunchedEffect`, mova lógica para `ViewModel` |
| `SurfaceFlinger CPU Deadline Missed` | O compositor do sistema estava lento | Reduza o número de layers, evite overdraw |
| `SurfaceFlinger GPU Deadline Missed` | A renderização da GPU demorou muito | Simplifique shaders, reduza complexidade visual, use hardware layers |
| `Buffering` | App produz frames mais rápido do que o display consome | Geralmente benigno |

---

### Bateria

```
## Bateria

| Métrica             | Valor    |
|---------------------|----------|
| Carga drenada       | 284 mC   |
| Duração do trace    | 60s      |
| Taxa média de drain | 4,7 mC/s |

### Top Consumidores
| Componente | Consumo estimado |
|------------|-----------------|
| CPU (big)  | 180 mW          |
| GPU        | 95 mW           |
| Memória    | 40 mW           |
```

**Referência de consumo típico:**

| Estado do app | Consumo total típico |
|---|---|
| App em idle | 5–20 mW |
| App ativo (UI, rede) | 100–300 mW |
| Vídeo / jogo | 500–2000 mW |

**Contadores principais:**

| Contador | Significado |
|---|---|
| `batt_charge_uah` | Carga da bateria em µAh — o delta ao longo do trace = consumo |
| `batt_current_ua` | Corrente instantânea em µA — negativo = descarregando |
| Power rails (`cpu.big`, `gpu`, etc.) | Consumo por subsistema em mW (devices Qualcomm/Tensor) |

**O que observar:**
- `CPU (big)` dominando → operações computacionalmente caras nos cores de alto desempenho; considere `THREAD_PRIORITY_BACKGROUND` para trabalho não crítico
- Drain alto em repouso → wake locks, sync agendado, acesso a localização em background
- GPU alta mesmo em telas simples → overdraw, layouts complexos, animações desnecessárias

---

### Recomendações

```
## Recomendações

1. **Mova a decodificação de imagens para fora da main thread** — `ImageDecoder.decode` foi chamado
   98 vezes na main thread, contribuindo para o P95 de 48ms. Use Coil ou Glide com carregamento
   baseado em coroutines.

2. **Reduza recomposições do Compose** — Recomposer mostra 201 amostras. Audite leituras de state
   em composables, aplique `@Stable` em data classes e use `remember` para cálculos custosos.

3. **Corrija memory leak no ImageLoader** — Bytes não liberados cresceram de 12 MB para 31 MB
   durante o trace. Verifique se `BitmapPool.clear()` é chamado em `onStop()` / `onDestroy()`.
```

Cada recomendação contém:
- **Título** — o que corrigir
- **Evidência** — o que o trace mostrou e a métrica específica que acionou o alerta
- **Ação** — um passo concreto para resolver o problema

---

## Referência de métricas

### Checklist de triagem rápida

Use esta sequência ao receber um relatório pela primeira vez:

1. **Frames** → `% dropados > 1%`? Se sim, verifique a timeline de CPU e as causas de jank.
2. **CPU** → A main thread está acima de 20% do total de CPU? Se sim, procure chamadas bloqueantes.
3. **Memória** → Os bytes não liberados estão crescendo ao longo do tempo? Se sim, há um leak.
4. **Bateria** → A taxa de drain está acima do esperado para o estado do app? Se sim, verifique wake locks e atividade em background.

### Perfetto UI

Para investigação profunda além do relatório, abra o arquivo `.pb` em [perfetto.dev/ui](https://perfetto.dev/ui):
- **Flame chart** → visualize a hierarquia completa de callstacks
- **Thread state** → veja exatamente quando as threads estão rodando, dormindo ou bloqueadas
- **SQL query** → execute queries customizadas via Trace Processor integrado

---

## Solução de problemas

| Erro | Causa | Solução |
|---|---|---|
| `no devices/emulators found` | Device não conectado ou depuração USB desativada | Execute `adb devices`, verifique as Opções do Desenvolvedor |
| `offline` em `adb devices` | Autorização não aceita no device | Desconecte e reconecte o USB, aceite o prompt no device |
| `ImportError: No module named 'perfetto'` | Biblioteca Python não instalada | `pip install perfetto` |
| `Error opening trace file` | Arquivo `.pb` corrompido ou versão incompatível | Valide o arquivo em [perfetto.dev/ui](https://perfetto.dev/ui) |
| Trace coletado mas dados zerados | Daemon `traced` não está rodando | `adb shell setprop persist.traced.enable 1 && adb shell start traced` |
| `permission denied` no device | App não é debuggable ou sem root | Use um build debug, ou `adb shell run-as <package>` |
| App não abre automaticamente | Package name incorreto ou app não instalado | Verifique com `adb shell pm list packages \| grep <nome>` |

---

## Desinstalar

```bash
npx perfetto-analyzer uninstall
```

Remove a skill de todos os diretórios dos agentes suportados.

---

## Licença

MIT
