#!/usr/bin/env python3
"""Resolve os runners do claude-workspaces para a pasta atual.

Lê ~/.config/claude-workspaces/workspaces.json, encontra o workspace cujas
pastas contêm o cwd informado (ou contêm/estão contidas nele) e imprime os
runners de nível-workspace (console_session_id vazio), deduplicados por nome.

Uso:
    resolve_runners.py [--cwd DIR] [NOME ...]

Sem NOME: lista todos os runners do workspace.
Com NOME(s): filtra por correspondência case-insensitive (substring) no nome.

Saída: JSON em stdout:
    {"workspace": "...", "matched_folder": "...", "runners": [
        {"name","start_cmd","cwd","env":{...},"enabled":bool}, ...]}

Em erro (nenhum workspace para o cwd): {"error": "...", "workspaces": [...]}
com exit code 2.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WS_FILE = Path.home() / ".config" / "claude-workspaces" / "workspaces.json"


def load_workspaces() -> list[dict]:
    raw = json.loads(WS_FILE.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("workspaces", [])
    return raw if isinstance(raw, list) else []


def folder_score(folder: str, cwd: str) -> int:
    """Comprimento do match se houver relação de prefixo entre folder e cwd."""
    f = os.path.realpath(folder)
    c = os.path.realpath(cwd)
    if c == f or c.startswith(f + os.sep) or f.startswith(c + os.sep):
        return len(os.path.commonpath([f, c]))
    return -1


def pick_workspace(workspaces: list[dict], cwd: str):
    best = None
    best_score = -1
    best_folder = ""
    for ws in workspaces:
        for folder in ws.get("folders", []):
            score = folder_score(folder, cwd)
            if score > best_score:
                best, best_score, best_folder = ws, score, folder
    return best, best_folder


def workspace_runners(ws: dict) -> list[dict]:
    """Runners de nível-workspace, deduplicados por nome (mantém o último)."""
    primary = (ws.get("folders") or [None])[0]
    by_name: dict[str, dict] = {}
    for r in ws.get("runners") or []:
        if (r.get("console_session_id") or "") != "":
            continue  # runner de console, não aparece no "play" do workspace
        by_name[r.get("name", "")] = {
            "name": r.get("name", ""),
            "start_cmd": r.get("start_cmd", ""),
            "cwd": r.get("cwd") or primary,
            "env": r.get("env") or {},
            "enabled": bool(r.get("enabled", True)),
        }
    return list(by_name.values())


def main() -> int:
    args = sys.argv[1:]
    cwd = os.getcwd()
    names: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--cwd":
            cwd = args[i + 1]
            i += 2
        else:
            names.append(args[i])
            i += 1

    workspaces = load_workspaces()
    ws, folder = pick_workspace(workspaces, cwd)
    if ws is None:
        json.dump(
            {
                "error": f"Nenhum workspace contém o cwd: {cwd}",
                "workspaces": [w.get("name") for w in workspaces],
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        return 2

    runners = workspace_runners(ws)
    if names:
        lowered = [n.lower() for n in names]
        runners = [r for r in runners if any(n in r["name"].lower() for n in lowered)]

    json.dump(
        {"workspace": ws.get("name"), "matched_folder": folder, "runners": runners},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
