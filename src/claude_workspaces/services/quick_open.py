"""Busca arquivos do workspace por padrão simples (case-insensitive).

Usa `git ls-files` em cada pasta — rápido, respeita .gitignore por
padrão. Em pastas que não são repo git, devolve vazio (não tenta cobrir
todos os cenários — basta o caso comum de Ctrl+P em projeto versionado).
"""

import logging
import subprocess

log = logging.getLogger(__name__)


def find_files(
    folders: list[str], pattern: str, max_results: int = 200
) -> list[str]:
    """Procura `pattern` (case-insensitive) nos paths listados pelo
    `git ls-files` de cada folder. Devolve até max_results paths
    absolutos."""
    needle = pattern.strip().lower()
    if not needle or not folders:
        return []
    matches: list[str] = []
    for folder in folders:
        try:
            r = subprocess.run(
                ["git", "ls-files"],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            log.debug("git ls-files falhou em %s", folder, exc_info=True)
            continue
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            if needle in line.lower():
                matches.append(f"{folder}/{line}")
                if len(matches) >= max_results:
                    return matches
    return matches
