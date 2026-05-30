"""Testes de plugins/manifest.py — dataclasses e lógica de permissões (puro)."""

from claude_workspaces.plugins.manifest import (
    Command,
    ConfigFieldType,
    Engine,
    ExtensionKind,
    FilesystemPermissions,
    Hook,
    Manifest,
    NetworkPermissions,
    Panel,
    PanelSlot,
    Permissions,
)

# ---------- StrEnums ----------

def test_extension_kind_values():
    assert ExtensionKind.COMMAND == "command"
    assert ExtensionKind.HOOK == "hook"
    assert ExtensionKind.PANEL == "panel"


def test_panel_slot_values():
    assert PanelSlot.SIDEBAR_TOP == "sidebar-top"
    assert PanelSlot.SIDEBAR_BOTTOM == "sidebar-bottom"
    assert PanelSlot.WORKSPACE_TAB == "workspace-tab"


def test_config_field_type_values():
    assert set(ConfigFieldType) == {
        ConfigFieldType.STRING,
        ConfigFieldType.INTEGER,
        ConfigFieldType.BOOLEAN,
        ConfigFieldType.ENUM,
    }


# ---------- FilesystemPermissions ----------

def test_fs_permissions_empty():
    assert FilesystemPermissions().is_empty() is True


def test_fs_permissions_not_empty_with_read():
    assert FilesystemPermissions(read=("/a",)).is_empty() is False


def test_fs_permissions_not_empty_with_write():
    assert FilesystemPermissions(write=("/b",)).is_empty() is False


# ---------- Permissions ----------

def test_can_read_path():
    assert Permissions().can_read_path() is False
    p = Permissions(filesystem=FilesystemPermissions(read=("/x",)))
    assert p.can_read_path() is True


def test_can_write_path():
    assert Permissions().can_write_path() is False
    p = Permissions(filesystem=FilesystemPermissions(write=("/x",)))
    assert p.can_write_path() is True


def test_can_use_network():
    assert Permissions().can_use_network() is False
    p = Permissions(network=NetworkPermissions(hosts=("example.com",)))
    assert p.can_use_network() is True


def test_workspace_allowed_all():
    # default workspaces == "all"
    assert Permissions().workspace_allowed("qualquer") is True


def test_workspace_allowed_tuple_membership():
    p = Permissions(workspaces=("ws-1", "ws-2"))
    assert p.workspace_allowed("ws-1") is True
    assert p.workspace_allowed("ws-9") is False


# ---------- Manifest ----------

def _manifest(**kw):
    defaults = dict(
        id="p", name="P", version="1.0.0", author="a", description="d",
        license="MIT", homepage=None, icon=None,
        engine=Engine(claude_workspaces=">=1.0.0"),
        commands=(), hooks=(), panels=(),
        permissions=Permissions(), config=(),
    )
    defaults.update(kw)
    return Manifest(**defaults)


def test_has_any_extension_false_when_all_empty():
    assert _manifest().has_any_extension() is False


def test_has_any_extension_true_with_command():
    m = _manifest(commands=(Command("c", "C", "h.run", ""),))
    assert m.has_any_extension() is True


def test_all_handlers_concatenates_in_order():
    m = _manifest(
        commands=(Command("c", "C", "cmd.handler", ""),),
        hooks=(Hook(event="session.changed", handler="hook.handler"),),
        panels=(Panel("pn", "Pn", PanelSlot.SIDEBAR_TOP, "panel.handler", "i"),),
    )
    assert m.all_handlers() == ["cmd.handler", "hook.handler", "panel.handler"]


def test_all_handlers_empty():
    assert _manifest().all_handlers() == []
