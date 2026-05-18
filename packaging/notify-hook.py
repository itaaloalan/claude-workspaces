#!/usr/bin/env python3
"""Hook do Claude Code (evento Stop) — dispara notify-send com o nome do
projeto e a última mensagem do usuário (que representa a tarefa em curso).

Instalado/removido pelo claude-workspaces via aba Configurações.

Lê textos das settings do app (app_name, formato do título, body padrão)
de ~/.config/claude-workspaces/settings.json. Como este script roda como
subprocess do Claude Code (sem acesso ao objeto Settings em memória), o
único caminho é reler do disco a cada turno.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_APP_NAME = "Claude Workspaces"
DEFAULT_TITLE_FORMAT = "Claude — {project}"
DEFAULT_BODY_PLACEHOLDER = "(turno encerrado)"


def _load_settings() -> dict:
    path = Path.home() / ".config" / "claude-workspaces" / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


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

    transcript_path = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()
    project_name = os.path.basename(cwd.rstrip("/")) or cwd

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

    try:
        subprocess.Popen(
            [
                "notify-send",
                "-a", app_name,
                "-i", "claude-workspaces",
                "-t", "5000",
                title,
                body,
            ]
        )
    except FileNotFoundError:
        pass
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
