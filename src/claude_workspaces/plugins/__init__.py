"""Subsistema de plugins.

Implementa a spec em `docs/PLUGIN_SPEC.md` v2.0 (plugins em Python).
A camada pública pra autores é `claude_workspaces.plugin_api`.

Componentes:
- manifest_loader / manifest: parser + tipos do plugin.yaml
- bundle_validator: layout do bundle (seção 2)
- static_analyzer: análise AST das proibições (seção 9)
- registry: instalar/desinstalar/listar plugins
- storage: persistência isolada por plugin (seção 5.5)
- events: bus thread-safe com throttle/debounce
- runtime: importlib + asyncio runner pros handlers"""

from __future__ import annotations

from .errors import (
    ManifestError,
    PermissionDeniedError,
    PluginError,
    RegistryError,
    StorageQuotaError,
    ValidationError,
)
from .events import (
    EVENT_CATALOG,
    HIGH_FREQUENCY_EVENTS,
    SESSION_STATUSES,
    EventBus,
    is_high_frequency,
    is_known_event,
)
from .manifest import (
    Command,
    ConfigField,
    ConfigFieldType,
    Engine,
    FilesystemPermissions,
    Hook,
    Manifest,
    NetworkPermissions,
    Panel,
    PanelSlot,
    Permissions,
)
from .manifest_loader import load_manifest
from .registry import HOST_VERSION, InstalledPlugin, PluginRegistry, plugins_dir
from .runtime import CtxFactory, PluginRuntime
from .storage import PluginStorage

__all__ = [
    # errors
    "PluginError",
    "ManifestError",
    "ValidationError",
    "RegistryError",
    "PermissionDeniedError",
    "StorageQuotaError",
    # manifest
    "Manifest",
    "Command",
    "Hook",
    "Panel",
    "Permissions",
    "FilesystemPermissions",
    "NetworkPermissions",
    "ConfigField",
    "ConfigFieldType",
    "PanelSlot",
    "Engine",
    # loader / registry / storage
    "load_manifest",
    "PluginRegistry",
    "InstalledPlugin",
    "plugins_dir",
    "HOST_VERSION",
    "PluginStorage",
    # events
    "EventBus",
    "EVENT_CATALOG",
    "HIGH_FREQUENCY_EVENTS",
    "SESSION_STATUSES",
    "is_known_event",
    "is_high_frequency",
    # runtime
    "PluginRuntime",
    "CtxFactory",
]
