"""Busca arquivos do workspace por padrão simples (case-insensitive).

Usa `git ls-files` em cada pasta — rápido, respeita .gitignore por
padrão. Em pastas que não são repo git, devolve vazio (não tenta cobrir
todos os cenários — basta o caso comum de Ctrl+P em projeto versionado).

Cache em memória de `git ls-files` por pasta com TTL curto: digitar 5
letras seguidas dispara 5 buscas em <1s — sem cache seriam 5 subprocesses
por pasta com saída idêntica.
"""

import logging
import subprocess
import time

log = logging.getLogger(__name__)

_CACHE_TTL_S = 5.0
# folder -> (timestamp, lines)
_cache: dict[str, tuple[float, list[str]]] = {}


def _list_files(folder: str) -> list[str] | None:
    now = time.monotonic()
    hit = _cache.get(folder)
    if hit and (now - hit[0]) < _CACHE_TTL_S:
        return hit[1]
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
        return None
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()
    _cache[folder] = (now, lines)
    return lines


def invalidate(folder: str | None = None) -> None:
    """Limpa o cache. Sem argumento: limpa tudo. Com folder: só aquele."""
    if folder is None:
        _cache.clear()
    else:
        _cache.pop(folder, None)


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
        lines = _list_files(folder)
        if lines is None:
            continue
        for line in lines:
            if needle in line.lower():
                matches.append(f"{folder}/{line}")
                if len(matches) >= max_results:
                    return matches
    return matches
