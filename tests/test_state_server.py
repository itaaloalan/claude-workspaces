"""Testes do StateServer (endpoint local pro plugin de browser)."""

import json
import socket
import urllib.request

from claude_workspaces.services.state_server import StateServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_state_server_serve_snapshot(tmp_path):
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({
            "ports": {
                "4202": {
                    "workspace": "map",
                    "runner": "web",
                    "scope": "console",
                    "cwd": str(tmp_path),  # não-git → branch vazio, worktree False
                    "state": "running",
                }
            }
        })
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/state.json", timeout=5
        ) as resp:
            assert resp.status == 200
            assert resp.headers["Access-Control-Allow-Origin"] == "*"
            data = json.loads(resp.read().decode("utf-8"))
        entry = data["ports"]["4202"]
        assert entry["workspace"] == "map"
        assert entry["runner"] == "web"
        assert entry["worktree"] is False
        assert "ts" in data
    finally:
        srv.stop()


def test_state_server_404_em_path_desconhecido():
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        import urllib.error
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/outra", timeout=5
            )
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_state_server_porta_ocupada_nao_explode():
    port = _free_port()
    srv1 = StateServer(port=port)
    assert srv1.start()
    try:
        srv2 = StateServer(port=port)
        assert srv2.start() is False
        assert srv2.running is False
    finally:
        srv1.stop()


def test_branch_info_em_worktree_real(tmp_path):
    """cwd que é git worktree de verdade → branch + worktree True."""
    import subprocess

    def run(args, cwd):
        subprocess.run(args, cwd=cwd, capture_output=True, check=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "config", "user.email", "t@t"], repo)
    run(["git", "config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("hi")
    run(["git", "add", "f.txt"], repo)
    run(["git", "commit", "-q", "-m", "init"], repo)
    from claude_workspaces.git_worktree import add_worktree
    ok, _msg, wt = add_worktree(str(repo), "feat/x")
    assert ok

    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({"ports": {"4202": {"workspace": "w", "runner": "web",
                                       "scope": "console", "cwd": str(wt),
                                       "state": "running"}}})
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/state.json", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entry = data["ports"]["4202"]
        assert entry["worktree"] is True
        assert entry["branch"] == "feat/x"
    finally:
        srv.stop()


def test_open_endpoint(tmp_path, monkeypatch):
    import urllib.error

    opened: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **kw):
            opened.append(list(args))

    import claude_workspaces.services.state_server as ss
    monkeypatch.setattr("subprocess.Popen", _FakePopen)

    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({"ports": {"4202": {"cwd": str(tmp_path)}}})
        # Porta conhecida → 204 + xdg-open no cwd do snapshot.
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/open?port=4202", timeout=5
        )
        assert req.status == 204
        assert opened == [["xdg-open", str(tmp_path)]]
        # Porta desconhecida → 404, sem abrir nada.
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/open?port=9999", timeout=5
            )
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(opened) == 1
    finally:
        srv.stop()
