"""Persiste a branch originária (base) de cada git worktree.

O git não registra de onde uma branch nasceu, então guardamos isso num
arquivo próprio em `config_dir()/worktree_bases.json`, indexado pelo path
ABSOLUTO (resolvido) da worktree:

    { "/home/italo/Projetos/map/map-api.claude/feat_x": "dev" }

Gravado na criação (app via `git_worktree.add_worktree`, skill via
`terminal_widget.adopt_worktree`) e consultado na renderização do header
do console pra mostrar `origem 🌱 <base>`.
"""

import json
import logging
from pathlib import Path

from .storage import config_dir

log = logging.getLogger(__name__)


def _bases_file() -> Path:
    return config_dir() / "worktree_bases.json"


def _norm(worktree_path: str) -> str:
    """Chave canônica: path absoluto resolvido. Cai pro path cru se o
    resolve falhar (ex.: dir já removido)."""
    try:
        return str(Path(worktree_path).resolve())
    except OSError:
        return worktree_path


def _load() -> dict[str, str]:
    path = _bases_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _save(bases: dict[str, str]) -> None:
    path = _bases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bases, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def set_base_branch(worktree_path: str, base: str) -> None:
    """Registra a branch base da worktree. No-op se `base` ou path vazios."""
    base = (base or "").strip()
    if not worktree_path or not base:
        return
    bases = _load()
    key = _norm(worktree_path)
    if bases.get(key) == base:
        return
    bases[key] = base
    _save(bases)


def get_base_branch(worktree_path: str) -> str:
    """Branch base da worktree, ou "" se desconhecida."""
    if not worktree_path:
        return ""
    return _load().get(_norm(worktree_path), "")


def forget_base_branch(worktree_path: str) -> None:
    """Remove o registro (ex.: worktree removida)."""
    if not worktree_path:
        return
    bases = _load()
    if bases.pop(_norm(worktree_path), None) is not None:
        _save(bases)
