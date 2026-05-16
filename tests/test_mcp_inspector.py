"""Testes do services/mcp_inspector."""

import json
from pathlib import Path

from claude_workspaces.services.mcp_inspector import (
    SCOPE_PROJECT,
    SCOPE_USER,
    TRANSPORT_HTTP,
    TRANSPORT_SSE,
    TRANSPORT_STDIO,
    list_servers,
    mask_sensitive,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_list_servers_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty")
    assert list_servers(None) == []


def test_list_servers_user_stdio(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {
            "pg": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres", "postgres://u:p@h/db"],
                "env": {"PGSSL": "1", "OTHER": "x"},
            },
        },
    })
    servers = list_servers(None)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "pg"
    assert s.scope == SCOPE_USER
    assert s.transport == TRANSPORT_STDIO
    assert s.command == "npx"
    assert "postgres" in s.args[1]
    assert set(s.env_keys) == {"PGSSL", "OTHER"}


def test_list_servers_project_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    proj = tmp_path / "proj"
    _write(proj / ".mcp.json", {
        "mcpServers": {
            "shared-tool": {
                "type": "sse",
                "url": "https://x.example/mcp",
            },
        },
    })
    servers = list_servers([str(proj)])
    assert len(servers) == 1
    s = servers[0]
    assert s.scope == SCOPE_PROJECT
    assert s.transport == TRANSPORT_SSE
    assert s.url == "https://x.example/mcp"


def test_list_servers_combines_user_and_project(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"u": {"command": "x", "args": []}},
    })
    proj = tmp_path / "p"
    _write(proj / ".mcp.json", {
        "mcpServers": {"p": {"command": "y", "args": []}},
    })
    servers = list_servers([str(proj)])
    names = {s.name for s in servers}
    assert names == {"u", "p"}


def test_default_transport_is_stdio(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"command": "y", "args": ["z"]}},
    })
    assert list_servers(None)[0].transport == TRANSPORT_STDIO


def test_invalid_transport_falls_back_to_stdio(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"type": "nonsense", "command": "y"}},
    })
    assert list_servers(None)[0].transport == TRANSPORT_STDIO


def test_skips_malformed_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"good": {"command": "y"}, "bad": "not a dict"},
    })
    names = [s.name for s in list_servers(None)]
    assert names == ["good"]


def test_skips_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".claude.json").write_text("{ broken json")
    assert list_servers(None) == []


def test_short_args_truncates(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"command": "y", "args": ["a" * 200]}},
    })
    s = list_servers(None)[0]
    assert len(s.short_args(80)) <= 80


def test_cli_preview_stdio(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"command": "npx", "args": ["-y", "pkg"]}},
    })
    s = list_servers(None)[0]
    assert s.cli_preview() == "npx -y pkg"


def test_cli_preview_sse(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"type": "sse", "url": "https://x"}},
    })
    s = list_servers(None)[0]
    assert "https://x" in s.cli_preview()


def test_mask_sensitive_url():
    assert "•••" in mask_sensitive("postgres://user:supersecret@host/db")
    # Sem credencial inline: não mexe
    assert mask_sensitive("https://example.com/x") == "https://example.com/x"


def test_transport_http(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _write(tmp_path / ".claude.json", {
        "mcpServers": {"x": {"type": "http", "url": "http://x"}},
    })
    assert list_servers(None)[0].transport == TRANSPORT_HTTP
