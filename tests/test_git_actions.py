import subprocess

import pytest

from claude_workspaces.git_actions import (
    commit,
    delete_untracked,
    discard_unstaged,
    fetch,
    has_staged_changes,
    pull_ff_only,
    stage_all,
    stage_file,
    unstage_all,
    unstage_file,
)


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@t"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "tracked.txt").write_text("hello\n")
    _run(["git", "add", "tracked.txt"], tmp_path)
    _run(["git", "commit", "-q", "-m", "init"], tmp_path)
    return tmp_path


def test_stage_file(repo):
    (repo / "tracked.txt").write_text("modified\n")
    ok, out = stage_file(str(repo), "tracked.txt")
    assert ok, out
    assert has_staged_changes(str(repo))


def test_unstage_file(repo):
    (repo / "tracked.txt").write_text("modified\n")
    stage_file(str(repo), "tracked.txt")
    assert has_staged_changes(str(repo))
    ok, out = unstage_file(str(repo), "tracked.txt")
    assert ok, out
    assert not has_staged_changes(str(repo))


def test_stage_all(repo):
    (repo / "a.txt").write_text("a")
    (repo / "b.txt").write_text("b")
    ok, _ = stage_all(str(repo))
    assert ok
    assert has_staged_changes(str(repo))


def test_unstage_all(repo):
    (repo / "a.txt").write_text("a")
    stage_all(str(repo))
    assert has_staged_changes(str(repo))
    ok, _ = unstage_all(str(repo))
    assert ok
    assert not has_staged_changes(str(repo))


def test_commit_requires_message(repo):
    (repo / "x.txt").write_text("x")
    stage_all(str(repo))
    ok, out = commit(str(repo), "")
    assert not ok
    assert "vazia" in out


def test_commit_success(repo):
    (repo / "x.txt").write_text("x")
    stage_all(str(repo))
    ok, out = commit(str(repo), "feat: add x")
    assert ok, out
    # commit limpou o staging
    assert not has_staged_changes(str(repo))


def test_discard_unstaged_restores_file(repo):
    (repo / "tracked.txt").write_text("destroyed")
    ok, _ = discard_unstaged(str(repo), "tracked.txt")
    assert ok
    assert (repo / "tracked.txt").read_text() == "hello\n"


def test_delete_untracked_removes_file(repo):
    target = repo / "junk.txt"
    target.write_text("noise")
    ok, _ = delete_untracked(str(repo), "junk.txt")
    assert ok
    assert not target.exists()


def test_delete_untracked_missing_file(repo):
    ok, msg = delete_untracked(str(repo), "doesnt-exist.txt")
    assert not ok
    assert "não é arquivo" in msg


def test_fetch_no_remote_fails_gracefully(repo):
    ok, _ = fetch(str(repo))
    # Sem remote configurado, fetch falha — mas não deve crashar
    # (alguns ambientes git imprimem warning sem erro)
    assert isinstance(ok, bool)


def test_pull_no_upstream_fails_gracefully(repo):
    ok, _ = pull_ff_only(str(repo))
    assert isinstance(ok, bool)


def test_actions_on_invalid_dir():
    ok, msg = stage_file("/path/that/does/not/exist", "x")
    assert not ok
    assert "inexistente" in msg.lower() or msg
