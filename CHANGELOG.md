# Changelog

## [1.0.6] - 2026-07-09

### Corrigido
- **`skill/CHANGELOG.md`** — CHANGELOG.md agora é instalado junto com a skill em `~/.claude/skills/perfetto-analyzer/CHANGELOG.md`, tornando a versão instalada visível sem precisar acessar o pacote npm.

## [1.0.5] - 2026-07-09

### Adicionado
- **`parse_perfetto_pb.py`** — Nova função `extract_thread_states()` que analisa a tabela `thread_state` do Perfetto: detecta I/O síncrono (estado `D` — uninterruptible sleep com `blocked_function`) e contenção de locks Java (slices de Monitor) por thread do app. Dado ausente nos traces anteriores que agora resolve o padrão "app travou mas o profiler não mostra nada".
- **`parse_perfetto_pb.py`** — Nova função `extract_cpu_megacycles()` usando o stdlib module `linux.cpu.utilization.process` (Android 12+). Retorna `[]` silenciosamente em versões anteriores.
- **`scripts/configs/oom.textproto`** — Novo tipo de trace `oom`: captura heap dump automaticamente ao momento do `OutOfMemoryError` via trigger `android.java_hprof.oom`. Aguarda até 1h o crash acontecer.
- **`analyze_metrics.py`** — Nova função `analyze_thread_states()` que gera issue `critical` quando a main thread está em I/O síncrono >10ms e `warning` para contenção de lock >5ms.
- **`generate_report.py`** — Nova seção **"Contenção de Threads"** na seção CPU com tabelas separadas para I/O bloqueante e Monitor contention.
- **`generate_report.py`** — Nova seção **"CPU Megacycles por Processo"** exibida quando disponível (Android 12+).
- **`collect_trace.py`** — Suporte ao tipo `oom`: modo especial sem countdown, aguarda o crash via Ctrl+C para cancelar.

### Referências (cookbooks do Perfetto que inspiraram estas melhorias)
- [Android Trace Analysis](https://perfetto.dev/docs/getting-started/android-trace-analysis)
- [Android OOM](https://perfetto.dev/docs/case-studies/android-outofmemoryerror)

## [1.0.4] - 2026-07-09

### Adicionado
- **`generate_report.py`** — Seção "Próximos Passos" agora inclui sugestões de traces de correlação automáticas quando fazem sentido:
  - `cpu` com Compose: sugere `frames` para confirmar se as recomposições causam drops reais
  - `cpu` com problemas: sugere `memory` para verificar heap churn nos mesmos hot paths
  - `frames` com jank: sugere `cpu` para identificar a callstack durante o deadline miss
  - `memory` com problemas: sugere `cpu` (hotspots de alocação) e `frames` (GC causando jank)
  - `battery` com problemas: sugere `cpu` e `all`
  - Trace tipo `all`: nenhuma sugestão (já captura tudo)

## [1.0.3] - 2026-07-09

### Corrigido
- **`parse_perfetto_pb.py`** — Dados de frames vazios em devices físicos. O fallback para Android < 12 usava correspondência exata do nome do slice (`'Choreographer#doFrame'`), mas em muitos devices físicos o nome vem com sufixo de frame number (`'Choreographer#doFrame 12345'`). Corrigido usando `LIKE 'Choreographer#doFrame%'` e `LIKE '%DrawFrame%'`.

## [1.0.2] - 2026-07-09

### Corrigido
- **`generate_report.py`** — `TypeError: 'NoneType' object is not subscriptable` ao gerar relatório de traces do tipo `battery`. Ocorria quando `thread_name` estava presente no dicionário com valor `None` (amostras de CPU sem thread associada). Corrigido em 4 ocorrências com `(value or "?")[:N]` no lugar de `value[:N]`.
- **`memory.textproto`** — App travava durante coleta de memória por causa do `block_client: true` no heapprofd, que bloqueava as threads do app a cada chamada `malloc()`. Alterado para `block_client: false`.
- **`memory.textproto`** — Reduzido `sampling_interval_bytes` de `4096` para `8192` para diminuir o overhead de profiling.
- **`all.textproto`** — Mesmas correções de `block_client` e `sampling_interval_bytes` aplicadas ao tipo `all`.
- **`all.textproto`** — Adicionado `android.java_hprof` que estava ausente: o tipo `all` não capturava objetos Java/Kotlin retidos no heap ART.

---

## [1.0.0] - 2026-07-09

### Adicionado
- Coleta automática de traces Perfetto via `adb` com suporte aos tipos `memory`, `cpu`, `frames`, `battery` e `all`.
- Abertura automática do app via launcher caso não esteja em execução no momento da coleta.
- Parsing de callstacks de CPU com CTE recursiva percorrendo a cadeia completa de `stack_profile_callsite` até profundidade 60.
- Identificação de hotspots do código do app filtrando frames pelo prefixo do package (com remoção de sufixos de build variant: `debug`, `release`, `staging`, etc.).
- Correlação de amostras de CPU com janelas de frames janked (`actual_frame_timeline_slice WHERE on_time_finish = 0`).
- Relatório markdown estruturado com Resumo Executivo, Memória, CPU, Frames, Bateria e Recomendações priorizadas por severidade.
- Instalação automática para 6 harness agents: Claude Code, GitHub Copilot, Cursor, Antigravity, Codex e Devin.
- CLI com comandos `install` e `uninstall` via `npx perfetto-analyzer`.
- Instalação automática via `postinstall` ao usar `npm install -g perfetto-analyzer`.
