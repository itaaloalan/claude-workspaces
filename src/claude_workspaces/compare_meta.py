"""Persiste a última branch base escolhida pra "comparar" cada repo.

Análogo a `worktree_meta.py` (branch de origem da worktree), mas guarda algo
diferente: a base que o usuário escolheu no modo "Comparar com branch base"
do `GitPanel`, indexada pelo path ABSOLUTO (resolvido) do repo/worktree, em
`config_dir()/compare_bases.json`:

    { "/home/italo/Projetos/map/map-api.claude/feat_x": "origin/dev" }

Assim, reabrir o modo comparação naquele repo já sugere a última base usada,
sem precisar escolher de novo toda vez.
"""

import json
import logging
from pathlib import Path

from .storage import config_dir

log = logging.getLogger(__name__)


def _bases_file() -> Path:
    return config_dir() / "compare_bases.json"


def _norm(folder: str) -> str:
    """Chave canônica: path absoluto resolvido. Cai pro path cru se o
    resolve falhar (ex.: dir já removido)."""
    try:
        return str(Path(folder).resolve())
    except OSError:
        return folder


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


def set_compare_base(folder: str, base: str) -> None:
    """Registra a última base de comparação escolhida pro repo. No-op se
    `base` ou `folder` vazios."""
    base = (base or "").strip()
    if not folder or not base:
        return
    bases = _load()
    key = _norm(folder)
    if bases.get(key) == base:
        return
    bases[key] = base
    _save(bases)


def get_compare_base(folder: str) -> str:
    """Última base de comparação escolhida pro repo, ou "" se desconhecida."""
    if not folder:
        return ""
    return _load().get(_norm(folder), "")


def forget_compare_base(folder: str) -> None:
    """Remove o registro (ex.: worktree removida)."""
    if not folder:
        return
    bases = _load()
    if bases.pop(_norm(folder), None) is not None:
        _save(bases)
