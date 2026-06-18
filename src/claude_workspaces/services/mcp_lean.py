"""Enxuga comandos MCP `npx`/`npm exec` para `node <entry>` direto.

Rodar um MCP stdio via `npx -y <pkg> ...` deixa um processo `npm exec`
**residente** (~128MB) como pai do `node` que de fato serve o protocolo (~58MB).
Com vários consoles abertos, cada um sobe seu próprio par — o wrapper npm sozinho
domina a RAM do app.

O pacote, depois do primeiro `npx`, já fica em disco no cache do npm
(`~/.npm/_npx/<hash>/node_modules/<pkg>`). Aqui resolvemos o entry-point real
desse pacote e reescrevemos o comando para `node <entry> <args...>`, eliminando o
processo npm. É puramente uma otimização de launch: se não der pra resolver
(cache ausente, sem `node` no PATH, formato inesperado), devolvemos o comando
original intacto — o `npx` repovoa o cache e na próxima já enxuga sozinho.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# Resolução é cara (glob + leitura de package.json); memoiza por nome de pacote.
_entry_cache: dict[str, str | None] = {}


def _npx_cache_roots() -> list[Path]:
    """Diretórios node_modules onde o npx deposita pacotes baixados via -y."""
    base = Path.home() / ".npm" / "_npx"
    if not base.is_dir():
        return []
    roots: list[Path] = []
    try:
        for entry in base.iterdir():
            nm = entry / "node_modules"
            if nm.is_dir():
                roots.append(nm)
    except OSError:
        return []
    return roots


def _entry_from_pkg_dir(pkg_dir: Path) -> str | None:
    """Resolve o arquivo JS de entrada de um diretório de pacote node, lendo o
    campo `bin` (preferido) ou `main`/index.js do package.json."""
    pj = pkg_dir / "package.json"
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    candidates: list[str] = []
    bin_field = data.get("bin")
    if isinstance(bin_field, str):
        candidates.append(bin_field)
    elif isinstance(bin_field, dict):
        # Prefere o bin cujo nome bate com o pacote; senão, qualquer um.
        name = str(data.get("name", "")).split("/")[-1]
        if name in bin_field:
            candidates.append(bin_field[name])
        candidates.extend(str(v) for v in bin_field.values())
    main = data.get("main")
    if isinstance(main, str):
        candidates.append(main)
    candidates.append("index.js")
    for rel in candidates:
        entry = (pkg_dir / rel).resolve()
        if entry.is_file():
            return str(entry)
    return None


def _pkg_name(spec: str) -> str:
    """Extrai o nome do pacote de um spec que pode trazer versão.

    'foo@1.2.3' → 'foo' ; '@scope/name@1.2.3' → '@scope/name'.
    """
    if spec.startswith("@"):
        scope, _, rest = spec.partition("/")
        name, _, _ver = rest.partition("@")
        return f"{scope}/{name}"
    return spec.partition("@")[0]


def _resolve_node_entry(pkg_name: str) -> str | None:
    """Acha o entry JS do pacote no cache do npx (mais recente primeiro)."""
    if pkg_name in _entry_cache:
        return _entry_cache[pkg_name]
    best: tuple[float, str] | None = None
    for nm in _npx_cache_roots():
        pkg_dir = nm.joinpath(*pkg_name.split("/"))
        if not pkg_dir.is_dir():
            continue
        entry = _entry_from_pkg_dir(pkg_dir)
        if entry is None:
            continue
        try:
            mtime = pkg_dir.stat().st_mtime
        except OSError:
            mtime = 0.0
        if best is None or mtime > best[0]:
            best = (mtime, entry)
    result = best[1] if best else None
    _entry_cache[pkg_name] = result
    return result


def _split_npx_args(command: str, args: list[str]) -> tuple[str, list[str]] | None:
    """Dado (command, args) de um launch npx/npm, retorna (pkg_spec, rest_args)
    ou None se não casar o formato `npx [-y] <pkg> <args...>`."""
    items = list(args)
    if command == "npm":
        # `npm exec <pkg> ...`
        if not items or items[0] != "exec":
            return None
        items = items[1:]
    # Pula flags de npx (-y/--yes/--quiet/-p/--package …). Para no 1º não-flag.
    i = 0
    while i < len(items):
        tok = items[i]
        if not tok.startswith("-"):
            break
        # Flags que consomem valor (raro aqui, mas seguro): --package <x>/-p <x>.
        if tok in ("-p", "--package") and i + 1 < len(items):
            i += 2
            continue
        i += 1
    if i >= len(items):
        return None
    return items[i], items[i + 1:]


def lean_mcp_cfg(cfg: dict) -> dict:
    """Devolve uma cópia de `cfg` com `npx/npm exec <pkg>` reescrito para
    `node <entry>` quando resolvível; senão devolve `cfg` inalterado."""
    if not isinstance(cfg, dict):
        return cfg
    command = cfg.get("command")
    args = cfg.get("args")
    if command not in ("npx", "npm") or not isinstance(args, list):
        return cfg
    parsed = _split_npx_args(command, [str(a) for a in args])
    if parsed is None:
        return cfg
    pkg_spec, rest = parsed
    entry = _resolve_node_entry(_pkg_name(pkg_spec))
    if entry is None:
        return cfg
    node = shutil.which("node")
    if not node:
        return cfg
    lean = dict(cfg)
    lean["command"] = node
    lean["args"] = [entry, *rest]
    log.debug("MCP enxugado: %s %s → node %s", command, pkg_spec, entry)
    return lean
