"""Bootstrap de configs locais pra worktree recém-criado.

Worktree novo faz checkout da config COMMITADA — o banco da aplicação
(application-dev.yml, glassfish-resources.xml, .env…) pode apontar pra
outro lugar que não o ambiente atual do projeto. O repo PRINCIPAL é a
fonte da verdade (o /trocar-banco mantém a config dele em sincronia com
o MCP): copiamos por cima os arquivos conhecidos quando o conteúdo
difere, e o worktree nasce apontando pro mesmo banco/ambiente.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# Configs locais que carregam ambiente/banco — relativos à raiz do repo.
LOCAL_CONFIG_PATTERNS = [
    "CLAUDE.md",
    ".claude/settings.local.json",
    ".env",
    ".env.local",
    "src/main/resources/application*.yml",
    "src/main/resources/application*.yaml",
    "src/main/resources/application*.properties",
    "src/main/webapp/WEB-INF/glassfish-resources.xml",
    "appsettings*.json",
]


def sync_local_configs(repo_folder: str, worktree_path: str) -> list[str]:
    """Copia do repo principal pro worktree os configs locais quando o
    conteúdo difere (ou não existe no worktree). Cria diretórios; tolera
    erro por arquivo (loga e segue). Retorna os relpaths copiados."""
    copied: list[str] = []
    repo = Path(repo_folder)
    wt = Path(worktree_path)
    if not repo.is_dir() or not wt.is_dir():
        return copied
    for pattern in LOCAL_CONFIG_PATTERNS:
        for src in sorted(repo.glob(pattern)):
            if not src.is_file():
                continue
            rel = src.relative_to(repo)
            dst = wt / rel
            try:
                if dst.is_file() and dst.read_bytes() == src.read_bytes():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(str(rel))
            except OSError:
                log.warning(
                    "sync de config local falhou: %s → %s", src, dst,
                    exc_info=True,
                )
    if copied:
        log.info(
            "worktree %s: %d config(s) sincronizadas do principal: %s",
            wt.name, len(copied), ", ".join(copied),
        )
    return copied
