"""Loader + validador de `plugin.yaml`.

Implementa as regras da seção 3 da spec. Erros são coletados e devolvidos
em batch (`ValidationError.errors`) — a UI mostra todos de uma vez, em vez
de obrigar o autor a corrigir um por um."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import semver
from .errors import ManifestError, ValidationError
from .events import EVENT_CATALOG, HIGH_FREQUENCY_EVENTS, is_known_event
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

# Regex da spec.
_PLUGIN_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")
_COMMAND_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PANEL_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_CONFIG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # snake_case
_HOSTNAME_RE = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$"
)
_SPDX_RE = re.compile(r"^[A-Za-z0-9.\-+]+$")  # validação básica de SPDX-ID

_MAX_DESCRIPTION_LEN = 200
_MAX_THROTTLE_MS = 60_000

_DEFAULT_HANDLER_DIRS = {
    "commands": "./src/commands/",
    "hooks": "./src/hooks/",
    "panels": "./src/panels/",
}


def load_manifest(bundle_dir: Path) -> Manifest:
    """Lê e valida `plugin.yaml`. Retorna `Manifest` tipado ou levanta erro.

    `bundle_dir` é a raiz do bundle (deve conter `plugin.yaml`)."""
    if not bundle_dir.exists():
        raise ManifestError(f"Diretório do plugin não existe: {bundle_dir}")
    if not bundle_dir.is_dir():
        raise ManifestError(f"Caminho não é um diretório: {bundle_dir}")

    manifest_path = bundle_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise ManifestError(f"plugin.yaml não encontrado em {bundle_dir}")

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"Não consegui ler {manifest_path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ManifestError(f"YAML inválido em {manifest_path}: {e}") from e

    if not isinstance(data, dict):
        raise ValidationError(["plugin.yaml precisa ser um mapa YAML (chaves no topo)"])

    errs: list[str] = []
    manifest = _build_manifest(data, errs)
    if errs:
        raise ValidationError(errs)
    return manifest  # type: ignore[return-value]


# ----- builders -----------------------------------------------------------


def _build_manifest(data: dict[str, Any], errs: list[str]) -> Manifest | None:
    plugin_id = _str_field(data, "id", errs)
    name = _str_field(data, "name", errs)
    version = _str_field(data, "version", errs)
    author = _str_field(data, "author", errs)
    description = _str_field(data, "description", errs)
    license_ = _str_field(data, "license", errs)

    # Identidade — checagens específicas
    if plugin_id and not _PLUGIN_ID_RE.match(plugin_id):
        errs.append(
            f"id {plugin_id!r} não bate com reverse-DNS "
            f"(regex {_PLUGIN_ID_RE.pattern})"
        )
    if version:
        try:
            semver.parse_version(version)
        except ValueError as e:
            errs.append(f"version inválido: {e}")
    if description and len(description) > _MAX_DESCRIPTION_LEN:
        errs.append(
            f"description tem {len(description)} caracteres "
            f"(máx {_MAX_DESCRIPTION_LEN})"
        )
    if license_ and not _SPDX_RE.match(license_):
        errs.append(f"license {license_!r} não parece um SPDX-ID válido")

    # Opcionais
    homepage = data.get("homepage")
    if homepage is not None and not isinstance(homepage, str):
        errs.append("homepage precisa ser string")
        homepage = None
    elif homepage and not homepage.startswith("https://"):
        errs.append(f"homepage precisa começar com https:// (recebi {homepage!r})")

    icon = data.get("icon")
    if icon is not None and not isinstance(icon, str):
        errs.append("icon precisa ser caminho relativo (string)")
        icon = None

    # Engine
    engine = _build_engine(data.get("engine"), errs)

    # Extensions
    ext = data.get("extensions") or {}
    if not isinstance(ext, dict):
        errs.append("extensions precisa ser um mapa")
        ext = {}

    commands = _build_commands(ext.get("commands") or [], errs)
    hooks = _build_hooks(ext.get("hooks") or [], errs)
    panels = _build_panels(ext.get("panels") or [], errs)

    if not commands and not hooks and not panels:
        errs.append(
            "extensions vazio — declare pelo menos um command, hook ou panel"
        )

    # Permissions (obrigatório, mesmo que vazio)
    permissions = _build_permissions(data.get("permissions"), errs)

    # Config (opcional)
    config = _build_config(data.get("config") or [], errs)

    # Metadados gerados pelo host nunca devem vir no input
    for forbidden in ("generated-by", "generated-at", "checksum"):
        if forbidden in data:
            errs.append(
                f"{forbidden!r} é preenchido pelo host — não envie no manifesto"
            )

    if errs:
        return None

    return Manifest(
        id=plugin_id or "",
        name=name or "",
        version=version or "",
        author=author or "",
        description=description or "",
        license=license_ or "",
        homepage=homepage,
        icon=icon,
        engine=engine,  # type: ignore[arg-type]
        commands=tuple(commands),
        hooks=tuple(hooks),
        panels=tuple(panels),
        permissions=permissions,
        config=tuple(config),
    )


def _build_engine(data: Any, errs: list[str]) -> Engine | None:
    if not isinstance(data, dict):
        errs.append("engine obrigatório (mapa com claude-workspaces)")
        return None
    range_expr = data.get("claude-workspaces")
    if not isinstance(range_expr, str) or not range_expr.strip():
        errs.append("engine.claude-workspaces obrigatório (string com range SemVer)")
        return None
    try:
        semver.parse_range(range_expr)
    except ValueError as e:
        errs.append(f"engine.claude-workspaces inválido: {e}")
        return None
    return Engine(claude_workspaces=range_expr.strip())


def _build_commands(items: Any, errs: list[str]) -> list[Command]:
    if not isinstance(items, list):
        errs.append("extensions.commands precisa ser lista")
        return []
    out: list[Command] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errs.append(f"commands[{i}] precisa ser mapa")
            continue
        cmd_id = item.get("id", "")
        title = item.get("title", "")
        handler = item.get("handler", "")
        desc = item.get("description", "")
        if not isinstance(cmd_id, str) or not _COMMAND_ID_RE.match(cmd_id):
            errs.append(
                f"commands[{i}].id inválido: {cmd_id!r} "
                f"(regex {_COMMAND_ID_RE.pattern})"
            )
            continue
        if cmd_id in seen:
            errs.append(f"commands[{i}].id duplicado: {cmd_id!r}")
            continue
        seen.add(cmd_id)
        if not isinstance(title, str) or not title.strip():
            errs.append(f"commands[{i}].title obrigatório")
            continue
        if not _is_valid_handler_path(handler, "commands"):
            errs.append(
                f"commands[{i}].handler inválido: {handler!r} "
                f"(esperado começar com {_DEFAULT_HANDLER_DIRS['commands']})"
            )
            continue
        if not isinstance(desc, str) or not desc.strip():
            errs.append(f"commands[{i}].description obrigatório")
            continue
        out.append(Command(id=cmd_id, title=title, handler=handler, description=desc))
    return out


def _build_hooks(items: Any, errs: list[str]) -> list[Hook]:
    if not isinstance(items, list):
        errs.append("extensions.hooks precisa ser lista")
        return []
    out: list[Hook] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errs.append(f"hooks[{i}] precisa ser mapa")
            continue
        event = item.get("event", "")
        handler = item.get("handler", "")
        throttle = item.get("throttle-ms", 0) or 0
        debounce = item.get("debounce-ms", 0) or 0
        if not isinstance(event, str) or not event.strip():
            errs.append(f"hooks[{i}].event obrigatório")
            continue
        if not is_known_event(event):
            known = ", ".join(sorted(EVENT_CATALOG))
            errs.append(
                f"hooks[{i}].event desconhecido: {event!r} (válidos: {known})"
            )
            continue
        if not _is_valid_handler_path(handler, "hooks"):
            errs.append(
                f"hooks[{i}].handler inválido: {handler!r} "
                f"(esperado começar com {_DEFAULT_HANDLER_DIRS['hooks']})"
            )
            continue
        if not isinstance(throttle, int) or throttle < 0:
            errs.append(f"hooks[{i}].throttle-ms precisa ser inteiro ≥ 0")
            continue
        if not isinstance(debounce, int) or debounce < 0:
            errs.append(f"hooks[{i}].debounce-ms precisa ser inteiro ≥ 0")
            continue
        if throttle and debounce:
            errs.append(
                f"hooks[{i}]: throttle-ms e debounce-ms são exclusivos (declare só um)"
            )
            continue
        if throttle > _MAX_THROTTLE_MS:
            errs.append(
                f"hooks[{i}].throttle-ms = {throttle} excede o máximo de "
                f"{_MAX_THROTTLE_MS}"
            )
            continue
        if event in HIGH_FREQUENCY_EVENTS and not throttle and not debounce:
            errs.append(
                f"hooks[{i}]: evento {event!r} é alta frequência — "
                f"throttle-ms ou debounce-ms é obrigatório"
            )
            continue
        out.append(
            Hook(event=event, handler=handler, throttle_ms=throttle, debounce_ms=debounce)
        )
    return out


def _build_panels(items: Any, errs: list[str]) -> list[Panel]:
    if not isinstance(items, list):
        errs.append("extensions.panels precisa ser lista")
        return []
    out: list[Panel] = []
    seen: set[str] = set()
    valid_slots = {s.value for s in PanelSlot}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errs.append(f"panels[{i}] precisa ser mapa")
            continue
        panel_id = item.get("id", "")
        title = item.get("title", "")
        slot = item.get("slot", "")
        handler = item.get("handler", "")
        icon = item.get("icon", "")
        if not isinstance(panel_id, str) or not _PANEL_ID_RE.match(panel_id):
            errs.append(
                f"panels[{i}].id inválido: {panel_id!r} "
                f"(regex {_PANEL_ID_RE.pattern})"
            )
            continue
        if panel_id in seen:
            errs.append(f"panels[{i}].id duplicado: {panel_id!r}")
            continue
        seen.add(panel_id)
        if not isinstance(title, str) or not title.strip():
            errs.append(f"panels[{i}].title obrigatório")
            continue
        if slot not in valid_slots:
            errs.append(
                f"panels[{i}].slot inválido: {slot!r} (válidos: {sorted(valid_slots)})"
            )
            continue
        if not _is_valid_handler_path(handler, "panels"):
            errs.append(
                f"panels[{i}].handler inválido: {handler!r} "
                f"(esperado começar com {_DEFAULT_HANDLER_DIRS['panels']})"
            )
            continue
        if not isinstance(icon, str) or not icon.strip():
            errs.append(f"panels[{i}].icon obrigatório (caminho relativo)")
            continue
        out.append(
            Panel(
                id=panel_id,
                title=title,
                slot=PanelSlot(slot),
                handler=handler,
                icon=icon,
            )
        )
    return out


def _build_permissions(data: Any, errs: list[str]) -> Permissions:
    if data is None:
        errs.append("permissions obrigatório (mesmo que vazio)")
        return Permissions()
    if not isinstance(data, dict):
        errs.append("permissions precisa ser mapa")
        return Permissions()

    fs_data = data.get("filesystem") or {}
    if not isinstance(fs_data, dict):
        errs.append("permissions.filesystem precisa ser mapa")
        fs_data = {}
    read = _str_list(fs_data.get("read"), "permissions.filesystem.read", errs)
    write = _str_list(fs_data.get("write"), "permissions.filesystem.write", errs)
    fs = FilesystemPermissions(read=tuple(read), write=tuple(write))

    net_data = data.get("network") or {}
    if not isinstance(net_data, dict):
        errs.append("permissions.network precisa ser mapa")
        net_data = {}
    hosts = _str_list(net_data.get("hosts"), "permissions.network.hosts", errs)
    for h in hosts:
        if "*" in h:
            errs.append(
                f"permissions.network.hosts: domínios não aceitam wildcards (recebi {h!r})"
            )
        elif not _HOSTNAME_RE.match(h):
            errs.append(f"permissions.network.hosts: domínio inválido: {h!r}")
    net = NetworkPermissions(hosts=tuple(hosts))

    notifications = data.get("notifications", False)
    if not isinstance(notifications, bool):
        errs.append("permissions.notifications precisa ser boolean")
        notifications = False

    workspaces = data.get("workspaces", "all")
    if workspaces == "all":
        ws_value: str | tuple[str, ...] = "all"
    elif isinstance(workspaces, list):
        for w in workspaces:
            if not isinstance(w, str) or not w.strip():
                errs.append("permissions.workspaces: IDs devem ser strings não-vazias")
                break
        ws_value = tuple(str(w) for w in workspaces)
    else:
        errs.append("permissions.workspaces deve ser 'all' ou lista de IDs")
        ws_value = "all"

    return Permissions(
        filesystem=fs,
        network=net,
        notifications=notifications,
        workspaces=ws_value,
    )


def _build_config(items: Any, errs: list[str]) -> list[ConfigField]:
    if not isinstance(items, list):
        errs.append("config precisa ser lista")
        return []
    out: list[ConfigField] = []
    seen_keys: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errs.append(f"config[{i}] precisa ser mapa")
            continue
        key = item.get("key", "")
        type_ = item.get("type", "")
        default = item.get("default")
        label = item.get("label", "")
        required = item.get("required", False)
        if not isinstance(key, str) or not _CONFIG_KEY_RE.match(key):
            errs.append(
                f"config[{i}].key inválido: {key!r} (snake_case: regex {_CONFIG_KEY_RE.pattern})"
            )
            continue
        if key in seen_keys:
            errs.append(f"config[{i}].key duplicado: {key!r}")
            continue
        seen_keys.add(key)
        if type_ not in {t.value for t in ConfigFieldType}:
            errs.append(
                f"config[{i}].type inválido: {type_!r} "
                f"(válidos: string, integer, boolean, enum)"
            )
            continue
        if not isinstance(label, str) or not label.strip():
            errs.append(f"config[{i}].label obrigatório (PT-BR)")
            continue
        if not isinstance(required, bool):
            errs.append(f"config[{i}].required precisa ser boolean")
            continue
        field_type = ConfigFieldType(type_)
        # type-specific
        min_v = item.get("min")
        max_v = item.get("max")
        options_raw = item.get("options")
        multiline = item.get("multiline", False)

        if field_type == ConfigFieldType.INTEGER:
            if not isinstance(default, int) or isinstance(default, bool):
                errs.append(f"config[{i}].default precisa ser inteiro")
                continue
            if min_v is not None and not isinstance(min_v, int):
                errs.append(f"config[{i}].min precisa ser inteiro")
                continue
            if max_v is not None and not isinstance(max_v, int):
                errs.append(f"config[{i}].max precisa ser inteiro")
                continue
            if min_v is not None and default < min_v:
                errs.append(f"config[{i}].default ({default}) < min ({min_v})")
                continue
            if max_v is not None and default > max_v:
                errs.append(f"config[{i}].default ({default}) > max ({max_v})")
                continue
        elif field_type == ConfigFieldType.BOOLEAN:
            if not isinstance(default, bool):
                errs.append(f"config[{i}].default precisa ser boolean")
                continue
        elif field_type == ConfigFieldType.STRING:
            if not isinstance(default, str):
                errs.append(f"config[{i}].default precisa ser string")
                continue
            if not isinstance(multiline, bool):
                errs.append(f"config[{i}].multiline precisa ser boolean")
                continue
        elif field_type == ConfigFieldType.ENUM:
            if not isinstance(options_raw, list) or not options_raw:
                errs.append(f"config[{i}].options obrigatório (lista não-vazia) para enum")
                continue
            options = tuple(str(o) for o in options_raw)
            if default not in options:
                errs.append(
                    f"config[{i}].default ({default!r}) não está em options ({list(options)})"
                )
                continue

        out.append(
            ConfigField(
                key=key,
                type=field_type,
                default=default,
                label=label,
                required=required,
                min=min_v if isinstance(min_v, int) else None,
                max=max_v if isinstance(max_v, int) else None,
                options=tuple(str(o) for o in options_raw) if isinstance(options_raw, list) else (),
                multiline=bool(multiline) if isinstance(multiline, bool) else False,
            )
        )
    return out


# ----- helpers ------------------------------------------------------------


def _str_field(data: dict[str, Any], key: str, errs: list[str]) -> str | None:
    val = data.get(key)
    if val is None or val == "":
        errs.append(f"{key} obrigatório")
        return None
    if not isinstance(val, str):
        errs.append(f"{key} precisa ser string")
        return None
    return val


def _str_list(value: Any, field_name: str, errs: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errs.append(f"{field_name} precisa ser lista")
        return []
    out: list[str] = []
    for i, v in enumerate(value):
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{field_name}[{i}] precisa ser string não-vazia")
            continue
        out.append(v)
    return out


def _is_valid_handler_path(path: Any, kind: str) -> bool:
    expected_prefix = _DEFAULT_HANDLER_DIRS[kind]
    if not isinstance(path, str):
        return False
    if not path.startswith(expected_prefix):
        return False
    if not path.endswith(".py"):
        return False
    # sem segmentos perigosos
    if ".." in path.split("/"):
        return False
    return True
