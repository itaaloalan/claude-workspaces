"""Detecção A — served_proc: o processo que escuta a porta roda do worktree
esperado? Os helpers de processo (ss/lsof//proc) são mockados; a comparação
de git-dir usa repos git de verdade."""

import subprocess

import pytest

from claude_workspaces.services import served_proc as sp


def _git_init(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return str(path)


def test_mismatch_when_served_from_other_repo(tmp_path, monkeypatch):
    expected = _git_init(tmp_path / "worktree")
    served = _git_init(tmp_path / "main_repo")
    monkeypatch.setattr(sp, "listening_pid", lambda port: 4242)
    monkeypatch.setattr(sp, "process_cwd", lambda pid: served)
    info = sp.served_mismatch(expected, 8088)
    assert info["served_pid"] == 4242
    assert info["served_mismatch"] is True


def test_no_mismatch_when_served_from_same_repo(tmp_path, monkeypatch):
    expected = _git_init(tmp_path / "wt")
    monkeypatch.setattr(sp, "listening_pid", lambda port: 99)
    # Servido de uma SUBPASTA do mesmo repo → mesmo git-dir → sem aviso.
    sub = tmp_path / "wt" / "src"
    sub.mkdir()
    monkeypatch.setattr(sp, "process_cwd", lambda pid: str(sub))
    assert sp.served_mismatch(expected, 8088)["served_mismatch"] is False


def test_no_mismatch_when_served_not_a_git_dir(tmp_path, monkeypatch):
    expected = _git_init(tmp_path / "wt")
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(sp, "listening_pid", lambda port: 7)
    monkeypatch.setattr(sp, "process_cwd", lambda pid: str(plain))
    # Conservador: served fora de repo git → não acusa (evita falso alarme).
    assert sp.served_mismatch(expected, 8088)["served_mismatch"] is False


def test_no_pid_no_mismatch(monkeypatch):
    monkeypatch.setattr(sp, "listening_pid", lambda port: None)
    info = sp.served_mismatch("/some/cwd", 8088)
    assert info["served_pid"] is None
    assert info["served_mismatch"] is False
