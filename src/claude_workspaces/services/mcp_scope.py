"""Escopo de servidores MCP por workspace.

Sem isto, toda sessão `claude` sobe TODOS os MCP globais de ~/.claude.json — com
6 MCP postgres e várias sessões abertas, são dezenas de processos node (gargalo
de memória). Aqui resolvemos quais MCP cada workspace precisa e geramos um
arquivo de config dedicado que o launch passa via `--mcp-config <file>
--strict-mcp-config` (o Claude então ignora o global e usa só esses).

Resolução (Workspace.mcp_servers):
  None  → auto-inferir pelo nome/pastas do workspace
  []    → nenhum MCP (arquivo com mcpServers vazio = strict vazio)
  [...] → exatamente esses (filtrados pelos que existem no global)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from .. import mcp_manager
from ..models import Workspace
from ..storage import config_dir

log = logging.getLogger(__name__)


def _norm(s: str) -> str:
    """Normaliza pra casar nomes: minúsculo, só alfanumérico."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match_names(tokens: set[str], available: list[str]) -> list[str]:
    """Casa um conjunto de tokens (já normalizados) contra os nomes dos MCP
    globais. Prioriza match EXATO (nome == token) — evita que 'ponto' case
    'ponto_antigo' por substring. Só cai pra substring (nos dois sentidos) se
    não houver nenhum exato."""
    tokens = {t for t in tokens if t}
    if not tokens or not available:
        return []
    exact = [name for name in available if _norm(name) in tokens]
    if exact:
        return exact
    hits: list[str] = []
    for name in available:
        n = _norm(name)
        if n and any(t in n or n in t for t in tokens):
            hits.append(name)
    return hits


def infer_mcp_servers(workspace: Workspace, available: list[str]) -> list[str]:
    """Infere os MCP do workspace casando nome + basenames das pastas contra os
    nomes dos servidores globais (ex.: workspace 'MAP' casa 'map')."""
    if not available:
        return []
    tokens = {_norm(workspace.name)}
    for folder in workspace.folders:
        tokens.add(_norm(os.path.basename(folder.rstrip("/"))))
    return _match_names(tokens, available)


def infer_mcp_servers_for_path(path: str, available: list[str]) -> list[str]:
    """Versão por diretório (pro `ia` manual no terminal): casa o basename do
    cwd + 1–2 componentes ancestrais contra os MCP globais. Ex.:
    /x/logique/map/map-api → tokens {mapapi, map, logique}."""
    if not available or not path:
        return []
    parts = [p for p in os.path.normpath(path).split(os.sep) if p]
    tokens = {_norm(p) for p in parts[-3:]}  # cwd + até 2 ancestrais
    return _match_names(tokens, available)


def resolve_mcp_servers(workspace: Workspace) -> list[str]:
    """Lista efetiva de MCP pro workspace (override explícito ou auto-infer),
    sempre filtrada pelos que de fato existem no global."""
    available = mcp_manager.list_mcp_names()
    if workspace.mcp_servers is None:
        return infer_mcp_servers(workspace, available)
    avail = set(available)
    return [n for n in workspace.mcp_servers if n in avail]


def _mcp_dir():
    d = config_dir() / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_config(names: list[str], filename: str) -> str | None:
    """Escreve {"mcpServers": {nome: cfg_global}} em mcp/<filename> e devolve o
    caminho. Devolve None em falha de escrita."""
    from .mcp_lean import lean_mcp_cfg

    servers: dict[str, dict] = {}
    for name in names:
        cfg = mcp_manager.get_mcp(name)
        if cfg:
            # Reescreve `npx -y <pkg>` → `node <entry>` quando possível, pra não
            # deixar o wrapper npm residente (~128MB) por console.
            servers[name] = lean_mcp_cfg(cfg)
    path = _mcp_dir() / filename
    try:
        path.write_text(
            json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8"
        )
    except OSError as e:
        log.error("Falha escrevendo config MCP %s: %s", filename, e)
        return None
    return str(path)


def write_workspace_mcp_config(workspace: Workspace) -> str | None:
    """Gera ~/.config/claude-workspaces/mcp/<id>.json com os MCP resolvidos do
    workspace e devolve o caminho pra usar em --mcp-config. Reescreve sempre
    (pega mudanças do global). Lista vazia → {"mcpServers": {}} (strict vazio =
    zero MCP na sessão)."""
    return _write_config(resolve_mcp_servers(workspace), f"{workspace.id}.json")


def write_path_mcp_config(path: str) -> str | None:
    """Pro `ia` manual: infere os MCP pela pasta `path` e gera um config
    dedicado. Devolve o caminho do config, ou None se NÃO houver match (aí o
    chamador cai no comportamento global — sem --mcp-config)."""
    available = mcp_manager.list_mcp_names()
    names = infer_mcp_servers_for_path(path, available)
    if not names:
        return None
    digest = hashlib.sha1(os.path.normpath(path).encode("utf-8")).hexdigest()[:12]
    return _write_config(names, f"cwd-{digest}.json")


def main(argv: list[str] | None = None) -> int:
    """CLI `claude-workspaces-mcp-scope [DIR]`: imprime o caminho de um config
    MCP escopado pela pasta (default = cwd). Não imprime nada se não houver
    match — o `ia` então roda o claude sem --mcp-config (global). Usado pela
    função fish `ia` pra escopar sessões manuais por diretório."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    cwd = args[0] if args else os.getcwd()
    try:
        path = write_path_mcp_config(cwd)
    except Exception:  # nunca quebra o `ia`
        return 0
    if path:
        print(path)
    return 0
