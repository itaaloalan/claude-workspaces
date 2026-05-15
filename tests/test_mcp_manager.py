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
