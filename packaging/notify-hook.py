#!/usr/bin/env python3
"""Hook do Claude Code (evento Stop) — dispara notificação nativa com o nome
do projeto, a última mensagem do usuário (que representa a tarefa em curso)
e um botão "Abrir console" que foca a aba dentro do claude-workspaces.

Instalado/removido pelo claude-workspaces via aba Configurações.

Lê textos das settings do app (app_name, formato do título, body padrão)
de ~/.config/claude-workspaces/settings.json. Como este script roda como
subprocess do Claude Code (sem acesso ao objeto Settings em memória), o
único caminho é reler do disco a cada turno.

A notificação é emitida via `gdbus call ... .Notify` com a ação
`open-console:<session_id>`. O app claude-workspaces escuta o sinal D-Bus
`ActionInvoked` globalmente: ao receber essa chave, localiza o terminal
cuja sessão atual (`claimed_session_id`) bate com `<session_id>` e foca
o workspace + aba correspondentes. Se `gdbus` não estiver disponível,
faz fallback para `notify-send` (sem botão).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_APP_NAME = "Claude Workspaces"
DEFAULT_TITLE_FORMAT = "Claude — {project}"
DEFAULT_BODY_PLACEHOLDER = "(turno encerrado)"
OPEN_ACTION_PREFIX = "open-console:"
OPEN_ACTION_LABEL = "Abrir console"

BUS_DEST = "org.freedesktop.Notifications"
BUS_PATH = "/org/freedesktop/Notifications"
BUS_IFACE = "org.freedesktop.Notifications"


def _load_settings() -> dict:
    path = Path.home() / ".config" / "claude-workspaces" / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _send_dbus(
    app_name: str,
    title: str,
    body: str,
    action_key: str,
    icon: str,
    timeout_ms: int,
    sound_name: str = "",
) -> bool:
    gdbus = shutil.which("gdbus")
    if not gdbus:
        return False
    if action_key:
        actions_arg = json.dumps([action_key, OPEN_ACTION_LABEL])
    else:
        actions_arg = "[]"
    if sound_name:
        safe_snd = sound_name.replace("'", "\\'")
        hints_arg = "{'sound-name': <'" + safe_snd + "'>}"
    else:
        hints_arg = "{}"
    try:
        proc = subprocess.run(
            [
                gdbus, "call",
                "--session",
                "--dest", BUS_DEST,
                "--object-path", BUS_PATH,
                "--method", f"{BUS_IFACE}.Notify",
                app_name,
                "0",
                icon,
                title,
                body,
                actions_arg,
                hints_arg,
                str(int(timeout_ms)),
            ],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def _send_notify_send(app_name: str, title: str, body: str, icon: str) -> None:
    try:
        subprocess.Popen(
            [
                "notify-send",
                "-a", app_name,
                "-i", icon,
                "-t", "5000",
                title,
                body,
            ]
        )
    except FileNotFoundError:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    settings = _load_settings()
    app_name = str(settings.get("notify_app_name") or DEFAULT_APP_NAME)
    title_fmt = str(settings.get("notify_hook_title_format") or DEFAULT_TITLE_FORMAT)
    default_body = str(
        settings.get("notify_hook_default_body") or DEFAULT_BODY_PLACEHOLDER
    )
    sound_enabled = bool(settings.get("notify_sound_enabled", True))
    sound_name = (
        str(settings.get("notify_sound_name") or "message-new-instant").strip()
        if sound_enabled else ""
    )

    transcript_path = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()
    project_name = os.path.basename(cwd.rstrip("/")) or cwd

    session_id = ""
    if transcript_path:
        session_id = Path(transcript_path).stem

    last_user_msg = ""
    if transcript_path:
        last_user_msg = _read_last_user_message(transcript_path)
    if not last_user_msg:
        last_user_msg = default_body

    try:
        title = title_fmt.format(project=project_name)
    except (KeyError, IndexError, ValueError):
        title = DEFAULT_TITLE_FORMAT.format(project=project_name)
    body = last_user_msg[:240]

    action_key = f"{OPEN_ACTION_PREFIX}{session_id}" if session_id else ""
    ok = _send_dbus(
        app_name, title, body, action_key, "claude-workspaces", 8000, sound_name
    )
    if not ok:
        _send_notify_send(app_name, title, body, "claude-workspaces")
    return 0


def _read_last_user_message(path: str) -> str:
    last = ""
    try:
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "user":
                    continue
                inner = msg.get("message")
                if not isinstance(inner, dict):
                    continue
                content = inner.get("content")
                if isinstance(content, str):
                    last = content.strip()
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            t = (c.get("text") or "").strip()
                            if t:
                                last = t
                                break
    except OSError:
        return ""
    return last


if __name__ == "__main__":
    sys.exit(main())
