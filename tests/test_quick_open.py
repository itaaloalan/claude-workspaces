import subprocess

import pytest

from claude_workspaces.services import quick_open


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@t"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "alpha.py").write_text("")
    (tmp_path / "beta.txt").write_text("")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "AlphaService.java").write_text("")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-q", "-m", "init"], tmp_path)
    return tmp_path


def test_empty_pattern_returns_empty(repo):
    assert quick_open.find_files([str(repo)], "") == []


def test_whitespace_pattern_returns_empty(repo):
    assert quick_open.find_files([str(repo)], "   ") == []


def test_no_folders_returns_empty():
    assert quick_open.find_files([], "anything") == []


def test_case_insensitive_match(repo):
    res = quick_open.find_files([str(repo)], "ALPHA")
    paths = sorted(res)
    assert paths == [f"{repo}/alpha.py", f"{repo}/src/AlphaService.java"]


def test_partial_match(repo):
    res = quick_open.find_files([str(repo)], "service")
    assert res == [f"{repo}/src/AlphaService.java"]


def test_no_match_empty(repo):
    assert quick_open.find_files([str(repo)], "zzzzz") == []


def test_non_repo_folder_skipped(tmp_path):
    (tmp_path / "alpha.py").write_text("")
    assert quick_open.find_files([str(tmp_path)], "alpha") == []


def test_aggregates_multiple_folders(repo, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _run(["git", "init", "-q", "-b", "main"], other)
    _run(["git", "config", "user.email", "t@t"], other)
    _run(["git", "config", "user.name", "t"], other)
    (other / "alpha.md").write_text("")
    _run(["git", "add", "."], other)
    _run(["git", "commit", "-q", "-m", "init"], other)

    res = sorted(quick_open.find_files([str(repo), str(other)], "alpha"))
    assert f"{repo}/alpha.py" in res
    assert f"{other}/alpha.md" in res


def test_max_results_limits_output(repo):
    # Cria muitos arquivos pra checar truncation
    for i in range(15):
        (repo / f"alpha_{i}.txt").write_text("")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "more"], repo)
    res = quick_open.find_files([str(repo)], "alpha", max_results=5)
    assert len(res) == 5


def test_git_missing_returns_empty(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(quick_open.subprocess, "run", boom)
    assert quick_open.find_files([str(repo)], "alpha") == []


def test_git_timeout_returns_empty(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)
    monkeypatch.setattr(quick_open.subprocess, "run", boom)
    assert quick_open.find_files([str(repo)], "alpha") == []
