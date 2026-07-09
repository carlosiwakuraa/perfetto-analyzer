# ADB Quick Start — Setup para Perfetto

## Instalação do adb

### macOS
```bash
brew install android-platform-tools
# ou baixar manualmente:
# https://developer.android.com/tools/releases/platform-tools
```

### Linux (Ubuntu/Debian)
```bash
sudo apt install android-tools-adb
```

### Verificar instalação
```bash
adb version
# Android Debug Bridge version 1.0.41
```

---

## Conectar device

### Via USB (recomendado para traces)

1. No Android: **Configurações → Sobre o dispositivo → Número da compilação** (toque 7x)
2. **Configurações → Opções do desenvolvedor → Depuração USB** → Ativar
3. Conectar cabo USB
4. Aceitar prompt "Permitir depuração USB?" no device (marque "Sempre permitir")

```bash
adb devices
# List of devices attached
# XXXXXXXX    device    ← OK
# XXXXXXXX    offline   ← Precisa aceitar no device
# XXXXXXXX    unauthorized  ← Precisa aceitar no device
```

### Via Wi-Fi (Android 11+)

1. **Opções do desenvolvedor → Depuração sem fio**
2. **Parear device** → anotar IP:porta
3. `adb pair <ip>:<porta>`
4. `adb connect <ip>:<porta>`

**Atenção:** Traces via Wi-Fi podem ser mais lentos para fazer `pull`. Para traces grandes (> 50 MB), prefira USB.

---

## Troubleshooting

### `no devices/emulators found`
```bash
# Reiniciar servidor adb
adb kill-server
adb start-server
adb devices
```

### `device offline` ou `unauthorized`
- Desconectar e reconectar cabo
- Aceitar prompt no device
- Se persistir: **Opções do desenvolvedor → Revogar autorizações de depuração USB** e re-autorizar

### `permission denied` ao executar Perfetto no device

O Perfetto requer permissão para coletar traces. Em Android 9+, o `traced` daemon já está rodando e aceita conexões de apps com permissão ou via shell.

```bash
# Verificar se traced está rodando
adb shell pgrep -a traced

# Se não estiver:
adb shell setprop persist.traced.enable 1
adb shell start traced
adb shell start traced_probes
```

Para heap profiling (heapprofd), o app precisa ser debuggable OU o device precisa estar rootado:
```bash
# Verificar se app é debuggable
adb shell pm dump <PACKAGE> | grep DEBUGGABLE
```

Se o app não for debuggable, use um build de debug ou:
```bash
# Root: habilitar profiling em release builds
adb shell setprop security.perf_harden 0
```

### `Error: Detach failed`

Alguns devices exigem:
```bash
adb shell "echo 0 > /proc/sys/kernel/perf_event_paranoid"
```

---

## Coleta manual via adb (referência)

O método mais robusto usa `adb exec-out` com stdin/stdout — sem gravar nada no device:

```bash
# Config via stdin, trace via stdout — sem permissões no device
cat frames.textproto | adb exec-out perfetto --txt -c - -o - > /tmp/trace.pb
```

Funciona em emuladores e devices físicos porque:
- `--txt` indica config em texto (textproto)
- `-c -` lê a config de stdin
- `-o -` escreve o trace em stdout
- `adb exec-out` transfere binário sem conversão de newlines (ao contrário de `adb shell`)

**Importante:** Não use `-o /sdcard/...` — o daemon do Perfetto roda com UID diferente do shell e não tem permissão de escrita no sdcard. Use stdout (`-o -`) ou `/data/misc/perfetto-traces/` (que exige pull separado).

---

## Comandos úteis durante troubleshooting de trace

```bash
# Ver logs do sistema em tempo real
adb logcat -s perfetto traced heapprofd

# Verificar se o traced daemon está rodando
adb shell pgrep -a traced

# Ativar daemon manualmente se não estiver rodando
adb shell setprop persist.traced.enable 1 && adb shell start traced

# Listar processos do app
adb shell ps -ef | grep <PACKAGE>

# Ver PID do app (útil para heapprofd)
adb shell pidof <PACKAGE>
```
