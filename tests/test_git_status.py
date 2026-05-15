import subprocess

import pytest

from claude_workspaces.git_status import get_status


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """Cria um repo git mínimo em tmp_path."""
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@t"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "file.txt").write_text("hello\n")
    _run(["git", "add", "file.txt"], tmp_path)
    _run(["git", "commit", "-q", "-m", "init"], tmp_path)
    return tmp_path


def test_non_existent_path():
    s = get_status("/path/that/does/not/exist/xyz")
    assert s.is_repo is False


def test_non_repo_dir(tmp_path):
    s = get_status(str(tmp_path))
    assert s.is_repo is False


def test_clean_repo(repo):
    s = get_status(str(repo))
    assert s.is_repo is True
    assert s.branch == "main"
    assert s.is_clean is True
    assert s.files == []


def test_modified_file(repo):
    (repo / "file.txt").write_text("modified\n")
    s = get_status(str(repo))
    assert s.is_repo is True
    assert s.is_clean is False
    assert len(s.files) == 1
    f = s.files[0]
    assert f.path == "file.txt"
    assert f.is_unstaged is True
    assert f.label() == "modificado"


def test_untracked_file(repo):
    (repo / "new.txt").write_text("x\n")
    s = get_status(str(repo))
    assert len(s.files) == 1
    f = s.files[0]
    assert f.is_untracked is True
    assert f.label() == "novo"
    assert f.path == "new.txt"


def test_staged_added(repo):
    (repo / "added.txt").write_text("y\n")
    _run(["git", "add", "added.txt"], repo)
    s = get_status(str(repo))
    assert len(s.files) == 1
    f = s.files[0]
    assert f.is_staged is True
    assert f.label() == "adicionado"


def test_file_with_spaces(repo):
    (repo / "file with space.txt").write_text("z\n")
    s = get_status(str(repo))
    paths = [f.path for f in s.files]
    assert "file with space.txt" in paths
