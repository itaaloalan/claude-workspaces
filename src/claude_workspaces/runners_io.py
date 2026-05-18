"""Import/export de RunnerConfigs como JSON portável.

Formato:
    {"runners": [ {name, start_cmd, stop_cmd, restart_cmd, cwd, env, enabled}, ... ]}

`id` é sempre regenerado na importação para evitar colisão entre máquinas.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import RunnerConfig, Workspace, _new_id


def export_runners(workspace: Workspace, path: str | Path) -> None:
    p = Path(path)
    payload = {
        "runners": [
            {
                k: v
                for k, v in r.to_dict().items()
                if k != "id"  # id é local; não exportar
            }
            for r in workspace.runners
        ],
    }
    p.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def import_runners(workspace: Workspace, path: str | Path) -> tuple[int, int]:
    """Importa runners, fazendo merge por nome.

    Retorna (adicionados, substituídos).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("runners")
    if not isinstance(items, list):
        raise ValueError("Arquivo inválido: campo 'runners' ausente.")

    by_name = {r.name: i for i, r in enumerate(workspace.runners)}
    added = 0
    replaced = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data["id"] = _new_id()  # nunca herda id do export
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
