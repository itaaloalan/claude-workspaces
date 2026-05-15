import json
from pathlib import Path

from .models import Workspace


def config_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces"


def workspaces_file() -> Path:
    return config_dir() / "workspaces.json"


def load_workspaces() -> list[Workspace]:
    path = workspaces_file()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Workspace.from_dict(w) for w in data.get("workspaces", [])]


def save_workspaces(workspaces: list[Workspace]) -> None:
    path = workspaces_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"workspaces": [w.to_dict() for w in workspaces]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
