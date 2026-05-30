import subprocess

import pytest

from claude_workspaces.git_status import (
    GitFile,
    GitStatus,
    _parse_porcelain_v2,
    get_status,
)


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


# ---------- GitFile (propriedades puras) ----------

def test_gitfile_is_staged():
    assert GitFile("M ", "a").is_staged is True
    assert GitFile(" M", "a").is_staged is False
    assert GitFile("??", "a").is_staged is False


def test_gitfile_is_unstaged():
    assert GitFile(" M", "a").is_unstaged is True
    assert GitFile("M ", "a").is_unstaged is False


def test_gitfile_is_untracked():
    assert GitFile("??", "a").is_untracked is True
    assert GitFile("M ", "a").is_untracked is False


@pytest.mark.parametrize("status,expected", [
    ("??", "novo"),
    ("MM", "mod (idx+ws)"),
    ("M ", "modificado"),
    (" M", "modificado"),
    ("A ", "adicionado"),
    ("D ", "deletado"),
    ("R ", "renomeado"),
    ("C ", "copiado"),
])
def test_gitfile_label(status, expected):
    assert GitFile(status, "a").label() == expected


# ---------- GitStatus.is_clean ----------

def test_gitstatus_is_clean():
    assert GitStatus(folder="/x", is_repo=True, files=[]).is_clean is True
    assert GitStatus(folder="/x", is_repo=True,
                     files=[GitFile("M ", "a")]).is_clean is False
    assert GitStatus(folder="/x", is_repo=False).is_clean is False


# ---------- _parse_porcelain_v2 (parser puro) ----------

def _porcelain(*entries: str) -> str:
    return "\0".join(entries) + "\0"


def test_parse_branch_and_ab():
    out = _porcelain(
        "# branch.oid abc123",
        "# branch.head main",
        "# branch.ab +2 -3",
    )
    branch, ahead, behind, files = _parse_porcelain_v2(out)
    assert branch == "main"
    assert ahead == 2
    assert behind == 3
    assert files == []


def test_parse_changed_file_staged_modified():
    out = _porcelain(
        "# branch.head main",
        "1 M. N... 100644 100644 100644 hH hI file1.txt",
    )
    _, _, _, files = _parse_porcelain_v2(out)
    assert len(files) == 1
    assert files[0].path == "file1.txt"
    assert files[0].status == "M "   # "." vira espaço
    assert files[0].is_staged is True


def test_parse_unstaged_modified():
    out = _porcelain("1 .M N... 100644 100644 100644 hH hI f.py")
    _, _, _, files = _parse_porcelain_v2(out)
    assert files[0].status == " M"
    assert files[0].is_unstaged is True


def test_parse_untracked():
    out = _porcelain("? novo.txt")
    _, _, _, files = _parse_porcelain_v2(out)
    assert files[0].status == "??"
    assert files[0].path == "novo.txt"


def test_parse_rename_consumes_original_path():
    out = _porcelain(
        "2 R. N... 100644 100644 100644 hH hI R100 novo.txt",
        "antigo.txt",  # path original — deve ser consumido, não virar arquivo
        "? extra.txt",
    )
    _, _, _, files = _parse_porcelain_v2(out)
    paths = [f.path for f in files]
    assert "novo.txt" in paths
    assert "antigo.txt" not in paths
    assert "extra.txt" in paths


def test_parse_detached_head():
    out = _porcelain(
        "# branch.oid deadbeefcafe",
        "# branch.head (detached)",
    )
    branch, _, _, _ = _parse_porcelain_v2(out)
    assert branch == "detached@deadbee"


def test_parse_empty_output():
    branch, ahead, behind, files = _parse_porcelain_v2("")
    assert branch == "?"
    assert (ahead, behind, files) == (0, 0, [])
