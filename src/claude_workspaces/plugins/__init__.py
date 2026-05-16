"""Subsistema de plugins.

Implementa a spec em `docs/PLUGIN_SPEC.md`. Esta camada é Python puro:
loader/validador/registry/storage/event-bus. O runtime de execução dos
handlers TypeScript é responsabilidade da fase 2 (não incluída ainda)."""

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
]
