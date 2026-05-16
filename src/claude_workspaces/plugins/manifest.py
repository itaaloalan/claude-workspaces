"""Dataclasses tipadas para o manifesto da seção 3 da spec.

Esses tipos representam o estado *já validado* (depois de `manifest_loader.load`).
Construir diretamente sem passar pelo loader é permitido em testes, mas a UI
e o registry sempre vão pelo loader pra garantir invariantes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExtensionKind(StrEnum):
    COMMAND = "command"
    HOOK = "hook"
    PANEL = "panel"


class PanelSlot(StrEnum):
    SIDEBAR_TOP = "sidebar-top"
    SIDEBAR_BOTTOM = "sidebar-bottom"
    WORKSPACE_TAB = "workspace-tab"


class ConfigFieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    handler: str
    description: str


@dataclass(frozen=True)
class Hook:
    event: str
    handler: str
    throttle_ms: int = 0
    debounce_ms: int = 0  # exclusivo com throttle_ms


@dataclass(frozen=True)
class Panel:
    id: str
    title: str
    slot: PanelSlot
    handler: str
    icon: str


@dataclass(frozen=True)
class ConfigField:
    key: str
    type: ConfigFieldType
    default: Any
    label: str
    required: bool = False
    min: int | None = None
    max: int | None = None
    options: tuple[str, ...] = ()
    multiline: bool = False


@dataclass(frozen=True)
class FilesystemPermissions:
    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not self.read and not self.write


@dataclass(frozen=True)
class NetworkPermissions:
    hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Permissions:
    """Permissões declaradas. Tudo o que não está aqui é negado por padrão."""

    filesystem: FilesystemPermissions = field(default_factory=FilesystemPermissions)
    network: NetworkPermissions = field(default_factory=NetworkPermissions)
    notifications: bool = False
    # "all" ou tupla de workspace IDs
    workspaces: str | tuple[str, ...] = "all"

    def can_read_path(self) -> bool:
        return bool(self.filesystem.read)

    def can_write_path(self) -> bool:
        return bool(self.filesystem.write)

    def can_use_network(self) -> bool:
        return bool(self.network.hosts)

    def workspace_allowed(self, workspace_id: str) -> bool:
        if self.workspaces == "all":
            return True
        if isinstance(self.workspaces, tuple):
            return workspace_id in self.workspaces
        return False


@dataclass(frozen=True)
class Engine:
    claude_workspaces: str  # range SemVer, ex: ">=1.0.0 <2.0.0"


@dataclass(frozen=True)
class Manifest:
    """Manifesto plenamente validado (seção 3 da spec)."""

    # Identidade
    id: str
    name: str
    version: str
    author: str
    description: str
    license: str
    # Opcionais
    homepage: str | None
    icon: str | None
    # Compat
    engine: Engine
    # Extensões — pelo menos uma das listas tem ≥1 item
    commands: tuple[Command, ...]
    hooks: tuple[Hook, ...]
    panels: tuple[Panel, ...]
    # Permissões
    permissions: Permissions
    # Config exposta ao usuário
    config: tuple[ConfigField, ...]

    def has_any_extension(self) -> bool:
        return bool(self.commands or self.hooks or self.panels)

    def all_handlers(self) -> list[str]:
        out: list[str] = []
        out.extend(c.handler for c in self.commands)
        out.extend(h.handler for h in self.hooks)
        out.extend(p.handler for p in self.panels)
        return out
