"""Testes do loader/validador do plugin.yaml (seção 3 da spec).

Cada teste foca num pedaço pequeno; quando uma falha esperada acontece,
verificamos a *mensagem* — não só a exceção — pra garantir que o autor
do plugin recebe orientação útil."""

from __future__ import annotations

import pytest

from claude_workspaces.plugins import (
    ConfigFieldType,
    ManifestError,
    PanelSlot,
    ValidationError,
    load_manifest,
)


def test_loads_valid_manifest(make_bundle):
    bundle = make_bundle()
    m = load_manifest(bundle)
    assert m.id == "com.exemplo.plug"
    assert m.version == "0.1.0"
    assert len(m.hooks) == 1
    assert m.hooks[0].event == "workspace.opened"
    assert m.permissions.workspaces == "all"


def test_missing_plugin_yaml(tmp_path):
    with pytest.raises(ManifestError, match="plugin.yaml não encontrado"):
        load_manifest(tmp_path)


def test_invalid_yaml(tmp_path):
    (tmp_path / "plugin.yaml").write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(ManifestError, match="YAML inválido"):
        load_manifest(tmp_path)


def test_invalid_plugin_id(make_bundle):
    bundle = make_bundle(overrides={"id": "Bad ID"})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("reverse-DNS" in e for e in ei.value.errors)


def test_invalid_version(make_bundle):
    bundle = make_bundle(overrides={"version": "1.0"})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("version inválido" in e for e in ei.value.errors)


def test_description_too_long(make_bundle):
    bundle = make_bundle(overrides={"description": "x" * 201})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("description" in e and "200" in e for e in ei.value.errors)


def test_engine_required(make_bundle):
    bundle = make_bundle(overrides={"engine": None})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("engine" in e for e in ei.value.errors)


def test_at_least_one_extension(make_bundle):
    bundle = make_bundle(
        overrides={"extensions": {"hooks": [], "commands": [], "panels": []}},
        skip_default_handler=True,
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("extensions vazio" in e for e in ei.value.errors)


def test_unknown_event(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {"event": "session.weird", "handler": "./src/hooks/on-open.ts"}
                ]
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("desconhecido" in e for e in ei.value.errors)


def test_high_frequency_event_requires_throttle(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {
                        "event": "session.message-sent",
                        "handler": "./src/hooks/on-open.ts",
                    }
                ]
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("alta frequência" in e for e in ei.value.errors)


def test_high_frequency_with_throttle_passes(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {
                        "event": "session.message-sent",
                        "handler": "./src/hooks/on-open.ts",
                        "throttle-ms": 1000,
                    }
                ]
            }
        }
    )
    m = load_manifest(bundle)
    assert m.hooks[0].throttle_ms == 1000


def test_throttle_and_debounce_exclusive(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {
                        "event": "session.message-sent",
                        "handler": "./src/hooks/on-open.ts",
                        "throttle-ms": 1000,
                        "debounce-ms": 500,
                    }
                ]
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("exclusivos" in e for e in ei.value.errors)


def test_invalid_handler_path(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {"event": "workspace.opened", "handler": "./elsewhere/x.ts"}
                ]
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("handler inválido" in e for e in ei.value.errors)


def test_handler_must_be_ts(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {"event": "workspace.opened", "handler": "./src/hooks/x.js"}
                ]
            }
        }
    )
    with pytest.raises(ValidationError):
        load_manifest(bundle)


def test_network_no_wildcards(make_bundle):
    bundle = make_bundle(
        overrides={
            "permissions": {
                "filesystem": {"read": [], "write": []},
                "network": {"hosts": ["*.example.com"]},
                "notifications": False,
                "workspaces": "all",
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("wildcard" in e for e in ei.value.errors)


def test_command_validates(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "commands": [
                    {
                        "id": "contar",
                        "title": "Contar",
                        "handler": "./src/commands/contar.ts",
                        "description": "Mostra contagem",
                    }
                ]
            }
        },
        extra_files={"src/commands/contar.ts": "export default async () => {};"},
        skip_default_handler=True,
    )
    m = load_manifest(bundle)
    assert m.commands[0].id == "contar"


def test_panel_validates(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "panels": [
                    {
                        "id": "stale",
                        "title": "Sessões paradas",
                        "slot": "sidebar-top",
                        "handler": "./src/panels/stale.ts",
                        "icon": "./assets/icon.svg",
                    }
                ]
            }
        },
        extra_files={
            "src/panels/stale.ts": "export default function (ctx: any) {}",
            "assets/icon.svg": "<svg/>",
        },
        skip_default_handler=True,
    )
    m = load_manifest(bundle)
    assert m.panels[0].slot == PanelSlot.SIDEBAR_TOP


def test_panel_invalid_slot(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "panels": [
                    {
                        "id": "stale",
                        "title": "X",
                        "slot": "lateral-right",
                        "handler": "./src/panels/stale.ts",
                        "icon": "./assets/icon.svg",
                    }
                ]
            }
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("slot inválido" in e for e in ei.value.errors)


def test_config_field_integer_default_in_range(make_bundle):
    bundle = make_bundle(
        overrides={
            "config": [
                {
                    "key": "threshold_minutes",
                    "type": "integer",
                    "default": 5,
                    "min": 1,
                    "max": 60,
                    "label": "Limiar",
                }
            ]
        }
    )
    m = load_manifest(bundle)
    assert m.config[0].type == ConfigFieldType.INTEGER
    assert m.config[0].default == 5


def test_config_field_integer_default_out_of_range(make_bundle):
    bundle = make_bundle(
        overrides={
            "config": [
                {
                    "key": "n",
                    "type": "integer",
                    "default": 100,
                    "min": 1,
                    "max": 60,
                    "label": "x",
                }
            ]
        }
    )
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("> max" in e for e in ei.value.errors)


def test_config_field_enum_default_in_options(make_bundle):
    bundle = make_bundle(
        overrides={
            "config": [
                {
                    "key": "mode",
                    "type": "enum",
                    "default": "off",
                    "options": ["off", "on"],
                    "label": "Modo",
                }
            ]
        }
    )
    m = load_manifest(bundle)
    assert m.config[0].options == ("off", "on")


def test_config_field_enum_default_not_in_options(make_bundle):
    bundle = make_bundle(
        overrides={
            "config": [
                {
                    "key": "mode",
                    "type": "enum",
                    "default": "maybe",
                    "options": ["off", "on"],
                    "label": "Modo",
                }
            ]
        }
    )
    with pytest.raises(ValidationError):
        load_manifest(bundle)


def test_host_metadata_rejected(make_bundle):
    bundle = make_bundle(overrides={"generated-by": "claude"})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("preenchido pelo host" in e for e in ei.value.errors)


def test_homepage_must_be_https(make_bundle):
    bundle = make_bundle(overrides={"homepage": "http://example.com"})
    with pytest.raises(ValidationError) as ei:
        load_manifest(bundle)
    assert any("https://" in e for e in ei.value.errors)
