"""Inspector dos MCP servers configurados.

Lê de 2 origens:
- user:    ~/.claude.json → "mcpServers" no top-level
- project: <ws>/.mcp.json → "mcpServers" no top-level

Devolve uma lista de McpServerEntry pra render.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SCOPE_USER = "user"
SCOPE_PROJECT = "project"

TRANSPORT_STDIO = "stdio"
TRANSPORT_SSE = "sse"
TRANSPORT_HTTP = "http"


@dataclass(frozen=True)
class McpServerEntry:
    name: str
    scope: str
    transport: str       # "stdio" | "sse" | "http"
    command: str         # vazio se transport != stdio
    args: tuple[str, ...]
    url: str             # vazio se transport == stdio
    env_keys: tuple[str, ...]   # apenas as chaves; valores não vazam pra UI
    source_file: Path
    raw: dict = field(repr=False)

    def short_args(self, limit: int = 80) -> str:
        s = " ".join(self.args)
        return s if len(s) <= limit else s[: limit - 1] + "…"

    def cli_preview(self) -> str:
        """Linha que aproxima como o Claude lança o server."""
        if self.transport == TRANSPORT_STDIO:
            parts = [self.command, *self.args]
            return " ".join(parts)
        return f"{self.transport.upper()}: {self.url}"


def _parse_server(name: str, raw: dict, scope: str, source: Path) -> McpServerEntry | None:
    if not isinstance(raw, dict):
        return None
    transport = str(raw.get("type", TRANSPORT_STDIO) or TRANSPORT_STDIO).lower()
    if transport not in {TRANSPORT_STDIO, TRANSPORT_SSE, TRANSPORT_HTTP}:
        transport = TRANSPORT_STDIO
    command = str(raw.get("command", "") or "")
    args_raw = raw.get("args", [])
    args = tuple(str(a) for a in args_raw) if isinstance(args_raw, list) else ()
    url = str(raw.get("url", "") or "")
    env = raw.get("env", {})
    env_keys = tuple(env.keys()) if isinstance(env, dict) else ()
    return McpServerEntry(
        name=name,
        scope=scope,
        transport=transport,
        command=command,
        args=args,
        url=url,
        env_keys=env_keys,
        source_file=source,
        raw=raw,
    )


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Skip %s: %s", path, e)
        return {}


def list_servers(workspace_folders: list[str] | None = None) -> list[McpServerEntry]:
    """Retorna todos os MCP servers configurados (user + project)."""
    out: list[McpServerEntry] = []
    user_file = Path.home() / ".claude.json"
    if user_file.exists():
        servers = _load_json(user_file).get("mcpServers")
        if isinstance(servers, dict):
            for name, raw in servers.items():
                entry = _parse_server(str(name), raw, SCOPE_USER, user_file)
                if entry:
                    out.append(entry)
    if workspace_folders:
        first = Path(workspace_folders[0])
        mcp_file = first / ".mcp.json"
        if mcp_file.exists():
            servers = _load_json(mcp_file).get("mcpServers")
            if isinstance(servers, dict):
                for name, raw in servers.items():
                    entry = _parse_server(str(name), raw, SCOPE_PROJECT, mcp_file)
                    if entry:
                        out.append(entry)
    return out


# Cache TTL por tuple(folders) dos nomes de MCP scope=project. Chamado a
# cada seleção (status bar + footer); lê .mcp.json do disco. 30s é fresco o
# bastante e some o IO repetido nos cliques.
_PROJECT_NAMES_TTL_S = 30.0
_project_names_cache: dict[tuple[str, ...], tuple[float, list[str]]] = {}


def list_project_server_names_cached(workspace_folders: list[str]) -> list[str]:
    """Nomes ordenados dos MCP servers scope=project, com cache TTL."""
    key = tuple(workspace_folders)
    now = time.monotonic()
    hit = _project_names_cache.get(key)
    if hit is not None and (now - hit[0]) < _PROJECT_NAMES_TTL_S:
        return list(hit[1])
    try:
        names = sorted({
            s.name for s in list_servers(list(workspace_folders))
            if s.scope == SCOPE_PROJECT
        })
    except Exception:
        log.exception("list_project_server_names_cached falhou")
        names = []
    # Poda expiradas no insert — chave por tuple(folders) muda quando o
    # workspace é editado, e a entrada antiga ficaria órfã pra sempre.
    for k in [
        k for k, v in _project_names_cache.items()
        if (now - v[0]) >= _PROJECT_NAMES_TTL_S
    ]:
        _project_names_cache.pop(k, None)
    _project_names_cache[key] = (now, list(names))
    return names


def mask_sensitive(text: str) -> str:
    """Mascara strings que parecem credenciais (URLs com user:pass@,
    tokens longos)."""
    import re
    text = re.sub(
        r"(postgres|postgresql|mysql|mongodb|redis)://([^:@\s]+):([^@\s]+)@",
        r"\1://\2:•••@",
        text,
    )
    return text
