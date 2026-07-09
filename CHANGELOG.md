# Changelog

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
