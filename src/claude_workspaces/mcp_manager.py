"""Gerenciamento de MCPs (Model Context Protocol) do Claude Code.

Lê e escreve ~/.claude.json preservando o resto do arquivo. Cobre só o
caso comum hoje: MCP postgres via @modelcontextprotocol/server-postgres,
configurado em user scope (mcpServers no top-level), com o nome do
workspace casando o nome do MCP — então cada workspace pode ter o seu
próprio MCP de banco isolado.
"""

import json
import logging
import shutil
import time
from pathlib import Path


log = logging.getLogger(__name__)


def claude_config_file() -> Path:
    return Path.home() / ".claude.json"


PG_PACKAGE = "@modelcontextprotocol/server-postgres"


def _load() -> dict:
    path = claude_config_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Falha lendo %s: %s", path, e)
        raise


def _save(data: dict) -> None:
    path = claude_config_file()
    # Backup curto antes de escrever — ~/.claude.json é o arquivo mais
    # importante do Claude (toda a história/projetos), corromper aqui
    # é caro
    if path.exists():
        backup = path.with_suffix(f".json.bak-{int(time.time())}")
        try:
            shutil.copy2(path, backup)
            # Mantém só os 3 backups mais novos
            backups = sorted(path.parent.glob(".claude.json.bak-*"))
            for old in backups[:-3]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except OSError:
            log.warning("Não consegui criar backup de %s", path, exc_info=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_mcp_names() -> list[str]:
    return list(_load().get("mcpServers", {}).keys())


def get_postgres_url(name: str) -> str | None:
    """Devolve a URL postgres do MCP `name`, ou None se não for um
    server postgres reconhecido."""
    data = _load()
    server = (data.get("mcpServers") or {}).get(name)
    if not server:
        return None
    if PG_PACKAGE not in server.get("args", []):
        return None
    for arg in server.get("args", []):
        if isinstance(arg, str) and arg.startswith(("postgres://", "postgresql://")):
            return arg
    return None


def is_postgres_mcp(name: str) -> bool:
    """True se o MCP `name` existe e é o postgres-server."""
    data = _load()
    server = (data.get("mcpServers") or {}).get(name)
    if not server:
        return False
    return PG_PACKAGE in server.get("args", [])


def set_postgres_mcp(name: str, postgres_url: str) -> None:
    """Cria ou atualiza o MCP postgres `name` com a URL fornecida."""
    if not name.strip():
        raise ValueError("Nome do MCP não pode ser vazio")
    if not postgres_url.startswith(("postgres://", "postgresql://")):
        raise ValueError("URL deve começar com postgres:// ou postgresql://")
    data = _load()
    data.setdefault("mcpServers", {})
    data["mcpServers"][name] = {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", PG_PACKAGE, postgres_url],
        "env": {},
    }
    _save(data)


def delete_mcp(name: str) -> bool:
    """Remove o MCP `name`. Devolve True se removeu, False se não existia."""
    data = _load()
    servers = data.get("mcpServers", {})
    if name not in servers:
        return False
    del servers[name]
    _save(data)
    return True


def mcp_exists(name: str) -> bool:
    return name in _load().get("mcpServers", {})


def mask_password(url: str) -> str:
    """Substitui a senha por ••• pra exibir na UI sem vazar credencial."""
    # postgres://user:pass@host:port/db
    try:
        scheme, rest = url.split("://", 1)
    except ValueError:
        return url
    if "@" not in rest:
        return url
    creds, host_part = rest.split("@", 1)
    if ":" in creds:
        user, _pwd = creds.split(":", 1)
        return f"{scheme}://{user}:•••@{host_part}"
    return url
