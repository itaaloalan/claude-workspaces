"""Import/export de RunnerConfigs como JSON portável.

Formato:
    {"runners": [ {name, start_cmd, stop_cmd, restart_cmd, cwd, env, enabled}, ... ]}

`id` é sempre regenerado na importação para evitar colisão entre máquinas.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import RunnerConfig, Workspace, _new_id


def export_runners(
    workspace: Workspace,
    path: str | Path,
    console_session_id: str = "",
) -> None:
    """Exporta runners filtrando por escopo.

    `console_session_id=""` exporta apenas runners do workspace.
    Quando fornecido, exporta apenas runners daquele console (mas
    sem persistir o `console_session_id` — o destino vai re-stampar
    no import).
    """
    p = Path(path)
    payload = {
        "runners": [
            {
                k: v
                for k, v in r.to_dict().items()
                # id é local; console_session_id é re-stampado no import
                # (não é portável entre máquinas/sessões).
                if k not in ("id", "console_session_id")
            }
            for r in workspace.runners
            if (r.console_session_id or "") == console_session_id
        ],
    }
    p.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def import_runners(
    workspace: Workspace,
    path: str | Path,
    console_session_id: str = "",
) -> tuple[int, int]:
    """Importa runners, fazendo merge por nome dentro do escopo informado.

    `console_session_id` define o escopo destino: vazio = workspace,
    preenchido = console. Merge por nome considera apenas runners do
    mesmo escopo (ex: "web" no workspace e "web" num console coexistem).

    Retorna (adicionados, substituídos).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("runners")
    if not isinstance(items, list):
        raise ValueError("Arquivo inválido: campo 'runners' ausente.")

    by_name: dict[str, int] = {
        r.name: i
        for i, r in enumerate(workspace.runners)
        if (r.console_session_id or "") == console_session_id
    }
    added = 0
    replaced = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data["id"] = _new_id()  # nunca herda id do export
        data["console_session_id"] = console_session_id  # stampa escopo destino
        new = RunnerConfig.from_dict(data)
        if new.name in by_name:
            idx = by_name[new.name]
            # Preserva id do existente pra não invalidar widgets em execução.
            new.id = workspace.runners[idx].id
            workspace.runners[idx] = new
            replaced += 1
        else:
            workspace.runners.append(new)
            by_name[new.name] = len(workspace.runners) - 1
            added += 1
    return added, replaced
