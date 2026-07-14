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
import threading
from pathlib import Path

from .storage import config_dir

log = logging.getLogger(__name__)


def _bases_file() -> Path:
    return config_dir() / "worktree_bases.json"


# Cache em memória de `_load()`, invalidado por mtime do arquivo. Sem isso,
# `get_base_branch` faz stat+read+json.loads em disco a cada chamada — e é
# chamado no hot path de `_refresh_terminal_pane_title` (poll de atividade
# a cada 250ms por console), o que aparecia como stalls de main thread no
# perf watchdog.
_cache_lock = threading.Lock()
_cache_mtime: float | None = None
_cache_data: dict[str, str] = {}


def _norm(worktree_path: str) -> str:
    """Chave canônica: path absoluto resolvido. Cai pro path cru se o
    resolve falhar (ex.: dir já removido)."""
    try:
        return str(Path(worktree_path).resolve())
    except OSError:
        return worktree_path


def _load() -> dict[str, str]:
    global _cache_mtime, _cache_data
    path = _bases_file()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        # Arquivo não existe (ainda) ou virou inacessível: cache vazio.
        with _cache_lock:
            _cache_mtime = None
            _cache_data = {}
        return {}

    with _cache_lock:
        if _cache_mtime == mtime:
            return _cache_data

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Não consegui ler %s", path)
        with _cache_lock:
            _cache_mtime = None
            _cache_data = {}
        return {}

    if not isinstance(data, dict):
        parsed: dict[str, str] = {}
    else:
        parsed = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    with _cache_lock:
        _cache_mtime = mtime
        _cache_data = parsed
    return parsed


def _save(bases: dict[str, str]) -> None:
    global _cache_mtime, _cache_data
    path = _bases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bases, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with _cache_lock:
        _cache_mtime = path.stat().st_mtime
        _cache_data = bases


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
