#!/usr/bin/env python3
"""Coleta um trace Perfetto de um device Android via adb."""

import argparse
import subprocess
import sys
import os
import time
import shutil

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS_DIR = os.path.join(SKILL_DIR, "scripts", "configs")


def run(cmd, check=True, capture=False):
    kwargs = {"check": check}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def check_adb():
    if not shutil.which("adb"):
        print("ERRO: 'adb' não encontrado no PATH.", file=sys.stderr)
        print("Instale Android SDK Platform-Tools e adicione ao PATH.", file=sys.stderr)
        sys.exit(1)


def check_device():
    result = run(["adb", "devices"], capture=True)
    lines = result.stdout.strip().splitlines()
    devices = [l for l in lines[1:] if l.strip() and "device" in l]
    if not devices:
        print("ERRO: Nenhum device Android conectado.", file=sys.stderr)
        print("Verifique:", file=sys.stderr)
        print("  1. Depuração USB ativada no device (Opções do Desenvolvedor)", file=sys.stderr)
        print("  2. Cabo USB conectado e aceito no device", file=sys.stderr)
        print("  3. Execute 'adb devices' para verificar", file=sys.stderr)
        sys.exit(1)
    if len(devices) > 1:
        print(f"AVISO: Múltiplos devices detectados. Usando o primeiro: {devices[0].split()[0]}", file=sys.stderr)
    return devices[0].split()[0]


def get_config_path(trace_type):
    config_map = {
        "memory": "memory.textproto",
        "cpu": "cpu.textproto",
        "frames": "frames.textproto",
        "battery": "battery.textproto",
        "all": "all.textproto",
    }
    filename = config_map.get(trace_type)
    if not filename:
        print(f"ERRO: Tipo de trace '{trace_type}' inválido.", file=sys.stderr)
        print(f"Tipos disponíveis: {', '.join(config_map.keys())}", file=sys.stderr)
        sys.exit(1)
    path = os.path.join(CONFIGS_DIR, filename)
    if not os.path.exists(path):
        print(f"ERRO: Config não encontrada: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def ensure_app_running(adb, package):
    """Verifica se o app está aberto; inicia via launcher se não estiver."""
    result = run(adb + ["shell", f"pidof {package}"], capture=True, check=False)
    pid = result.stdout.strip()

    if pid:
        print(f"App em execução (PID: {pid})")
        return

    print(f"App não está aberto. Iniciando {package}...")
    run(
        adb + ["shell", "monkey", "-p", package,
               "-c", "android.intent.category.LAUNCHER", "1"],
        capture=True,
        check=False,
    )

    # Aguarda até 15s para o processo aparecer
    for attempt in range(15):
        time.sleep(1)
        result = run(adb + ["shell", f"pidof {package}"], capture=True, check=False)
        if result.stdout.strip():
            print(f"App iniciado (PID: {result.stdout.strip()})")
            # Pausa extra para deixar a UI estabilizar antes de coletar
            time.sleep(2)
            return
        print(f"  Aguardando inicialização... {attempt + 1}s", end="\r", flush=True)

    print(f"\nAVISO: Não foi possível confirmar a abertura do app após 15s. Continuando mesmo assim.")


def inject_package(config_path, package, duration_ms):
    """Lê o textproto e injeta package e duração se necessário."""
    with open(config_path) as f:
        content = f.read()
    content = content.replace("__PACKAGE__", package)
    content = content.replace("__DURATION_MS__", str(duration_ms))
    tmp_config = "/tmp/perfetto_config_patched.textproto"
    with open(tmp_config, "w") as f:
        f.write(content)
    return tmp_config


# O daemon traced escreve em /data/misc/perfetto-traces/ — é o único path que ele tem acesso.
DEVICE_TRACE_PATH = "/data/misc/perfetto-traces/perfetto_trace.pb"


def collect_trace(device_id, config_path, duration_seconds, output_path):
    adb = ["adb", "-s", device_id]

    # Limpar arquivo anterior — se foi criado por outro UID, o daemon não consegue sobrescrever.
    run(adb + ["shell", f"rm -f {DEVICE_TRACE_PATH}"], check=False)

    print(f"[1/3] Coletando trace ({duration_seconds}s) — interaja com o app agora!")

    with open(config_path, "rb") as config_file:
        config_content = config_file.read()

    proc = subprocess.Popen(
        adb + ["shell", f"perfetto --txt -c - -o {DEVICE_TRACE_PATH}"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc.stdin.write(config_content)
    proc.stdin.close()

    # Countdown baseado em tempo real — atualiza só quando o segundo muda
    start = time.monotonic()
    last_sec = -1
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= duration_seconds:
            break
        current_sec = int(elapsed)
        if current_sec != last_sec:
            print(f"  ... {current_sec}/{duration_seconds}s", end="\r", flush=True)
            last_sec = current_sec
        time.sleep(0.1)
    print(f"  ... {duration_seconds}/{duration_seconds}s")
    print("Finalizando coleta...")

    # Aguarda o perfetto terminar com timeout fixo para evitar hang
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print("ERRO: Perfetto não finalizou em 20s após a coleta.", file=sys.stderr)
        sys.exit(1)

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode(errors="replace")
        print(f"ERRO ao coletar trace (exit {proc.returncode}): {stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"[2/3] Baixando trace do device...")
    run(adb + ["pull", DEVICE_TRACE_PATH, output_path])

    print(f"[3/3] Limpando arquivo do device...")
    run(adb + ["shell", f"rm -f {DEVICE_TRACE_PATH}"], check=False)

    size_kb = os.path.getsize(output_path) // 1024
    if size_kb == 0:
        print("ERRO: Trace vazio (0 bytes). Verifique se o traced daemon está ativo.", file=sys.stderr)
        print("Dica: adb shell 'setprop persist.traced.enable 1 && start traced'", file=sys.stderr)
        sys.exit(1)

    print(f"\nTrace coletado: {output_path} ({size_kb} KB)")


def main():
    parser = argparse.ArgumentParser(description="Coleta trace Perfetto via adb")
    parser.add_argument("--package", required=True, help="Package do app (ex: com.example.app)")
    parser.add_argument("--type", required=True, choices=["memory", "cpu", "frames", "battery", "all"],
                        dest="trace_type", help="Tipo de trace a coletar")
    parser.add_argument("--duration", type=int, default=30, help="Duração em segundos (padrão: 30)")
    parser.add_argument("--output", default="/tmp/perfetto_trace.pb", help="Caminho de saída do .pb")
    args = parser.parse_args()

    check_adb()
    device_id = check_device()
    adb = ["adb", "-s", device_id]

    print(f"Device: {device_id}")
    print(f"Package: {args.package}")
    print(f"Tipo: {args.trace_type}")
    print(f"Duração: {args.duration}s\n")

    ensure_app_running(adb, args.package)

    raw_config = get_config_path(args.trace_type)
    patched_config = inject_package(raw_config, args.package, args.duration * 1000)

    collect_trace(device_id, patched_config, args.duration, args.output)


if __name__ == "__main__":
    main()
