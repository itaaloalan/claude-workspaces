"""Gerenciamento de MCPs (Model Context Protocol) do Claude Code.

Lê e escreve ~/.claude.json preservando o resto do arquivo. Há duas APIs:

1. Helpers postgres (legado): set_postgres_mcp, get_postgres_url,
   is_postgres_mcp, mask_password. Mantidos pra compat — o McpDialog
   ainda usa essas funções.

2. API genérica: set_generic_mcp(name, command, args, env) +
   get_mcp(name). Suporta qualquer MCP server (filesystem, github,
   brave-search, etc.) — basta passar o command e args corretos. Veja
   MCP_PRESETS pra exemplos de configuração comuns.
"""

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def claude_config_file() -> Path:
    return Path.home() / ".claude.json"


def ai_config_file(backend: str = "claude") -> Path:
    """Retorna o arquivo de config MCP pro backend ativo."""
    if backend == "opencode":
        return Path.home() / ".config" / "opencode" / "opencode.jsonc"
    return Path.home() / ".claude.json"


PG_PACKAGE = "@modelcontextprotocol/server-postgres"


@dataclass(frozen=True)
class McpPreset:
    """Template pra um MCP server bem-conhecido.

    `args_template` pode conter placeholders `{placeholder_name}` que o
    UI preenche via prompt; `placeholders` lista (nome_placeholder,
    label_user, sensitive) para a UI saber o que pedir e se deve mascarar
    o input (tokens etc.).
    """

    id: str
    label: str
    description: str
    command: str
    args_template: list[str]
    env_template: dict[str, str] = field(default_factory=dict)
    # [(placeholder, label, sensitive)]
    placeholders: list[tuple[str, str, bool]] = field(default_factory=list)


# Presets de MCPs comuns. A UI pode renderizá-los como uma lista de
# "Adicionar MCP" e perguntar só os placeholders.
MCP_PRESETS: list[McpPreset] = [
    McpPreset(
        id="postgres",
        label="PostgreSQL",
        description="Query SQL read-only num banco PostgreSQL.",
        command="npx",
        args_template=["-y", PG_PACKAGE, "{url}"],
        placeholders=[("url", "URL postgres (postgres://user:pass@host/db)", True)],
    ),
    McpPreset(
        id="filesystem",
        label="Filesystem",
        description="Acesso de leitura/escrita a um diretório específico.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-filesystem", "{path}"],
        placeholders=[("path", "Pasta a expor (absoluta)", False)],
    ),
    McpPreset(
        id="github",
        label="GitHub",
        description="Issues/PRs/commits via API do GitHub (precisa PAT).",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-github"],
        env_template={"GITHUB_PERSONAL_ACCESS_TOKEN": "{token}"},
        placeholders=[("token", "GitHub Personal Access Token", True)],
    ),
    McpPreset(
        id="brave-search",
        label="Brave Search",
        description="Web search via Brave Search API.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-brave-search"],
        env_template={"BRAVE_API_KEY": "{api_key}"},
        placeholders=[("api_key", "Brave API key", True)],
    ),
    McpPreset(
        id="sequential-thinking",
        label="Sequential Thinking",
        description="Estrutura raciocínio passo-a-passo em problemas complexos.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-sequential-thinking"],
    ),
    McpPreset(
        id="memory",
        label="Memory",
        description="Knowledge graph local persistente para o Claude.",
        command="npx",
        args_template=["-y", "@modelcontextprotocol/server-memory"],
    ),
]


def preset_by_id(preset_id: str) -> McpPreset | None:
    return next((p for p in MCP_PRESETS if p.id == preset_id), None)


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


def set_generic_mcp(
    name: str,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    mcp_type: str = "stdio",
) -> None:
    """Cria ou atualiza um MCP arbitrário em ~/.claude.json.

    Use isso pra qualquer MCP que não seja postgres. Validação mínima:
    name não-vazio, command não-vazio. A UI deve confirmar o que está
    sendo enviado antes de chamar.
    """
    if not name.strip():
        raise ValueError("Nome do MCP não pode ser vazio")
    if not command.strip():
        raise ValueError("Command do MCP não pode ser vazio")
    data = _load()
    data.setdefault("mcpServers", {})
    entry: dict = {
        "type": mcp_type,
        "command": command,
        "args": list(args),
        "env": dict(env or {}),
    }
    data["mcpServers"][name] = entry
    _save(data)


def get_mcp(name: str) -> dict | None:
    """Devolve a config raw do MCP `name` (command/args/env/type) ou
    None se não existe."""
    data = _load()
    server = (data.get("mcpServers") or {}).get(name)
    if not isinstance(server, dict):
        return None
    return dict(server)


def instantiate_preset(
    preset: McpPreset, values: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Resolve os placeholders do preset com `values` e devolve
    (args_resolvidos, env_resolvido). Levanta KeyError se faltar
    placeholder declarado."""
    declared = {name for name, _label, _sens in preset.placeholders}
    missing = declared - values.keys()
    if missing:
        raise KeyError(f"Faltam valores pros placeholders: {sorted(missing)}")
    args = [a.format(**values) for a in preset.args_template]
    env = {k: v.format(**values) for k, v in preset.env_template.items()}
    return args, env


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
