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

import json
import logging
import re

from .. import mcp_manager
from ..models import Workspace
from ..storage import config_dir

log = logging.getLogger(__name__)


def _norm(s: str) -> str:
    """Normaliza pra casar nomes: minúsculo, só alfanumérico."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def infer_mcp_servers(workspace: Workspace, available: list[str]) -> list[str]:
    """Infere os MCP do workspace casando nome + basenames das pastas contra os
    nomes dos servidores globais. Match por substring normalizada nos dois
    sentidos (ex.: workspace 'MAP' casa 'map'; pasta 'sipe' casa 'sipepro')."""
    if not available:
        return []
    import os

    tokens = {_norm(workspace.name)}
    for folder in workspace.folders:
        tokens.add(_norm(os.path.basename(folder.rstrip("/"))))
    tokens.discard("")

    # Prioriza match EXATO (nome == token) — evita que 'ponto' case
    # 'ponto_antigo' por substring. Só cai pra substring se não houver exato.
    exact = [name for name in available if _norm(name) in tokens]
    if exact:
        return exact
    hits: list[str] = []
    for name in available:
        n = _norm(name)
        if n and any(t and (t in n or n in t) for t in tokens):
            hits.append(name)
    return hits


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


def write_workspace_mcp_config(workspace: Workspace) -> str | None:
    """Gera ~/.config/claude-workspaces/mcp/<id>.json com os MCP resolvidos do
    workspace e devolve o caminho (string) pra usar em --mcp-config. Reescreve
    sempre (pega mudanças do global). Lista vazia → {"mcpServers": {}} (strict
    vazio = zero MCP na sessão). Devolve None em caso de falha de escrita."""
    names = resolve_mcp_servers(workspace)
    servers: dict[str, dict] = {}
    for name in names:
        cfg = mcp_manager.get_mcp(name)
        if cfg:
            servers[name] = cfg
    path = _mcp_dir() / f"{workspace.id}.json"
    try:
        path.write_text(
            json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8"
        )
    except OSError as e:
        log.error("Falha escrevendo config MCP do workspace %s: %s", workspace.id, e)
        return None
    return str(path)
