"""API pública pra autores de plugins (seção 5 da spec).

Plugins importam daqui — nada mais. Esta camada é estável e segue SemVer.
Quebrar contrato aqui significa bumping do major version da spec.

A implementação concreta dos Protocols vive em `plugins/runtime.py`. O host
constrói instâncias com permissões pré-aplicadas e injeta em cada handler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# -------------------- payloads de eventos (seção 7) --------------------


@dataclass(frozen=True)
class SessionCreatedPayload:
    session_id: str
    workspace_id: str
    created_at: str  # ISO-8601


@dataclass(frozen=True)
class SessionStatusChangedPayload:
    session_id: str
    old_status: str
    new_status: str
    duration_ms: int


@dataclass(frozen=True)
class SessionMessageSentPayload:
    session_id: str
    message_id: str
    length: int


@dataclass(frozen=True)
class SessionCompletedPayload:
    session_id: str
    reason: str
    duration_ms: int


@dataclass(frozen=True)
class WorkspaceOpenedPayload:
    workspace_id: str


@dataclass(frozen=True)
class WorkspaceClosedPayload:
    workspace_id: str


@dataclass(frozen=True)
class CommitCreatedPayload:
    workspace_id: str
    sha: str
    message: str


@dataclass(frozen=True)
class PluginConfigChangedPayload:
    key: str
    old_value: Any
    new_value: Any


# -------------------- modelos retornados pelas APIs --------------------


@dataclass(frozen=True)
class Workspace:
    """View read-only de um workspace, do ponto de vista do plugin."""

    id: str
    name: str
    folders: tuple[str, ...]


@dataclass(frozen=True)
class Session:
    """View read-only de uma sessão Claude observada pelo host."""

    id: str
    workspace_id: str
    workspace_name: str
    status: str  # "running" | "awaiting-input" | "idle" | "completed" | "error"
    last_message: str | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Unsubscribe = Callable[[], None]


# -------------------- sub-protocolos do ctx (seção 5) --------------------


@runtime_checkable
class WorkspacesAPI(Protocol):
    async def list(self) -> list[Workspace]: ...
    async def current(self) -> Workspace | None: ...
    async def get(self, id: str) -> Workspace: ...


@runtime_checkable
class SessionsAPI(Protocol):
    async def list(self, *, status: str | None = None) -> list[Session]: ...
    async def get(self, id: str) -> Session: ...
    async def focus(self, id: str) -> None: ...


@runtime_checkable
class UIAPI(Protocol):
    async def notify(self, *, title: str, body: str, sound: bool = False) -> None: ...
    async def badge(self, *, count: int | None = None) -> None: ...
    async def toast(self, *, message: str, level: str = "info") -> None: ...


@runtime_checkable
class ConfigAPI(Protocol):
    async def get(self, key: str) -> Any: ...
    def on_change(
        self, cb: Callable[[str, Any], None]
    ) -> Unsubscribe: ...  # síncrono


@runtime_checkable
class StorageAPI(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...


@runtime_checkable
class FilesystemAPI(Protocol):
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> None: ...
    async def list(self, path: str) -> list[str]: ...


@runtime_checkable
class HttpAPI(Protocol):
    async def get(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> HttpResponse: ...
    async def post(
        self,
        url: str,
        *,
        body: bytes | str,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse: ...


class LogAPI(Protocol):
    """Síncrono por design — log nunca bloqueia handlers."""

    def info(self, msg: str, **data: Any) -> None: ...
    def warn(self, msg: str, **data: Any) -> None: ...
    def error(self, msg: str, **data: Any) -> None: ...


# -------------------- contexts injetados nos handlers --------------------


@runtime_checkable
class BaseContext(Protocol):
    """Conjunto comum a todos os handlers."""

    workspaces: WorkspacesAPI
    sessions: SessionsAPI
    ui: UIAPI
    config: ConfigAPI
    storage: StorageAPI
    fs: FilesystemAPI
    http: HttpAPI
    log: LogAPI


@runtime_checkable
class CommandContext(BaseContext, Protocol):
    """Injetado em `async def handler(ctx)` de commands."""


@runtime_checkable
class HookContext(BaseContext, Protocol):
    """Injetado em `async def handler(ctx, payload)` de hooks."""


@runtime_checkable
class PanelContext(BaseContext, Protocol):
    """Injetado em `def handler(ctx) -> QWidget` de panels.

    Diferente dos outros: panels são síncronos no boot (factory de widget),
    e usam `on_event` pra reagir a eventos depois."""

    def on_event(
        self,
        event: str,
        cb: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> Unsubscribe: ...


__all__ = [
    # Payloads
    "SessionCreatedPayload",
    "SessionStatusChangedPayload",
    "SessionMessageSentPayload",
    "SessionCompletedPayload",
    "WorkspaceOpenedPayload",
    "WorkspaceClosedPayload",
    "CommitCreatedPayload",
    "PluginConfigChangedPayload",
    # Models
    "Workspace",
    "Session",
    "HttpResponse",
    "Unsubscribe",
    # Sub-APIs
    "WorkspacesAPI",
    "SessionsAPI",
    "UIAPI",
    "ConfigAPI",
    "StorageAPI",
    "FilesystemAPI",
    "HttpAPI",
    "LogAPI",
    # Contexts
    "BaseContext",
    "CommandContext",
    "HookContext",
    "PanelContext",
]
