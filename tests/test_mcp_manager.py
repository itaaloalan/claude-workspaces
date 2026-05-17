import json

import pytest

from claude_workspaces import mcp_manager


@pytest.fixture
def fake_claude_json(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    monkeypatch.setattr(mcp_manager, "claude_config_file", lambda: path)
    return path


def test_no_config(fake_claude_json):
    assert mcp_manager.list_mcp_names() == []
    assert mcp_manager.mcp_exists("anything") is False


def test_set_postgres_creates_entry(fake_claude_json):
    mcp_manager.set_postgres_mcp("proj1", "postgresql://u:p@h:5432/db")
    data = json.loads(fake_claude_json.read_text())
    assert "proj1" in data["mcpServers"]
    entry = data["mcpServers"]["proj1"]
    assert entry["type"] == "stdio"
    assert entry["command"] == "npx"
    assert "@modelcontextprotocol/server-postgres" in entry["args"]
    assert "postgresql://u:p@h:5432/db" in entry["args"]


def test_set_postgres_preserves_other_top_level_keys(fake_claude_json):
    fake_claude_json.write_text(json.dumps({
        "userID": "abc",
        "projects": {"/a": {"foo": 1}},
        "mcpServers": {"keep_me": {"command": "x", "args": []}},
    }))
    mcp_manager.set_postgres_mcp("new", "postgres://x@y/z")
    data = json.loads(fake_claude_json.read_text())
    assert data["userID"] == "abc"
    assert data["projects"]["/a"]["foo"] == 1
    assert "keep_me" in data["mcpServers"]
    assert "new" in data["mcpServers"]


def test_set_postgres_rejects_invalid_url(fake_claude_json):
    with pytest.raises(ValueError):
        mcp_manager.set_postgres_mcp("p", "mysql://x")
    with pytest.raises(ValueError):
        mcp_manager.set_postgres_mcp("", "postgres://x")


def test_get_postgres_url(fake_claude_json):
    mcp_manager.set_postgres_mcp("x", "postgresql://a:b@h:5432/db")
    assert mcp_manager.get_postgres_url("x") == "postgresql://a:b@h:5432/db"
    assert mcp_manager.get_postgres_url("absent") is None


def test_is_postgres_mcp(fake_claude_json):
    mcp_manager.set_postgres_mcp("pg", "postgres://x@h/d")
    assert mcp_manager.is_postgres_mcp("pg") is True
    # MCP non-postgres
    data = json.loads(fake_claude_json.read_text())
    data["mcpServers"]["other"] = {"command": "node", "args": ["server.js"]}
    fake_claude_json.write_text(json.dumps(data))
    assert mcp_manager.is_postgres_mcp("other") is False


def test_delete_mcp(fake_claude_json):
    mcp_manager.set_postgres_mcp("x", "postgres://a@h/d")
    assert mcp_manager.delete_mcp("x") is True
    assert mcp_manager.delete_mcp("x") is False
    assert mcp_manager.mcp_exists("x") is False


def test_mask_password():
    assert mcp_manager.mask_password("postgresql://u:secret@h:5432/db") == \
        "postgresql://u:•••@h:5432/db"
    assert mcp_manager.mask_password("postgres://nouser_or_pwd@h/d") == \
        "postgres://nouser_or_pwd@h/d"
    assert mcp_manager.mask_password("not a url") == "not a url"


def test_backup_created_on_save(fake_claude_json):
    mcp_manager.set_postgres_mcp("first", "postgres://x@h/a")
    backups = list(fake_claude_json.parent.glob(".claude.json.bak-*"))
    # primeira escrita ainda não tinha algo pra backupear
    assert len(backups) == 0
    mcp_manager.set_postgres_mcp("second", "postgres://x@h/b")
    backups = list(fake_claude_json.parent.glob(".claude.json.bak-*"))
    assert len(backups) >= 1


# ---------- API genérica ----------

def test_set_generic_mcp_persists_full_payload(fake_claude_json):
    mcp_manager.set_generic_mcp(
        name="gh",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
    )
    data = json.loads(fake_claude_json.read_text())
    server = data["mcpServers"]["gh"]
    assert server["type"] == "stdio"
    assert server["command"] == "npx"
    assert server["args"] == ["-y", "@modelcontextprotocol/server-github"]
    assert server["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_xxx"


def test_set_generic_mcp_validates_name_and_command(fake_claude_json):
    with pytest.raises(ValueError):
        mcp_manager.set_generic_mcp("", "npx", ["x"])
    with pytest.raises(ValueError):
        mcp_manager.set_generic_mcp("name", "  ", ["x"])


def test_get_mcp_returns_dict_or_none(fake_claude_json):
    assert mcp_manager.get_mcp("doesnt-exist") is None
    mcp_manager.set_generic_mcp("memory", "npx", ["-y", "@mcp/memory"])
    got = mcp_manager.get_mcp("memory")
    assert got is not None
    assert got["command"] == "npx"
    assert got["args"] == ["-y", "@mcp/memory"]


def test_preset_by_id_lookup():
    assert mcp_manager.preset_by_id("postgres") is not None
    assert mcp_manager.preset_by_id("nope") is None


def test_preset_postgres_has_url_placeholder():
    p = mcp_manager.preset_by_id("postgres")
    assert p is not None
    names = {ph[0] for ph in p.placeholders}
    assert names == {"url"}
    # Confirma que o template realmente contém o placeholder
    assert "{url}" in p.args_template


def test_instantiate_preset_resolves_args(fake_claude_json):
    preset = mcp_manager.preset_by_id("postgres")
    assert preset is not None
    args, env = mcp_manager.instantiate_preset(preset, {"url": "postgres://x@h/db"})
    assert args == ["-y", mcp_manager.PG_PACKAGE, "postgres://x@h/db"]
    assert env == {}


def test_instantiate_preset_resolves_env(fake_claude_json):
    preset = mcp_manager.preset_by_id("github")
    assert preset is not None
    args, env = mcp_manager.instantiate_preset(preset, {"token": "ghp_xyz"})
    assert env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xyz"}
    assert "@modelcontextprotocol/server-github" in args


def test_instantiate_preset_raises_on_missing_value():
    preset = mcp_manager.preset_by_id("brave-search")
    assert preset is not None
    with pytest.raises(KeyError):
        mcp_manager.instantiate_preset(preset, {})


def test_install_preset_end_to_end(fake_claude_json):
    """Fluxo típico da UI: pega preset, resolve, salva."""
    preset = mcp_manager.preset_by_id("filesystem")
    assert preset is not None
    args, env = mcp_manager.instantiate_preset(preset, {"path": "/home/user/notes"})
    mcp_manager.set_generic_mcp(
        name="notes-fs",
        command=preset.command,
        args=args,
        env=env,
    )
    got = mcp_manager.get_mcp("notes-fs")
    assert got is not None
    assert "/home/user/notes" in got["args"]
