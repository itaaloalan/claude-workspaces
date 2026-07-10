import subprocess

import pytest

from claude_workspaces.git_status import (
    GitFile,
    GitStatus,
    _parse_porcelain_v2,
    get_compare_scan,
    get_diff_range,
    get_status,
    merge_base,
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


# ---------- comparação com branch base (merge_base / get_compare_scan) ----

@pytest.fixture
def feature_repo(repo):
    """`repo` (branch main, 1 commit) + branch `feature` com 1 commit próprio,
    1 mudança não commitada e 1 arquivo untracked; e um commit extra em
    `main` feito DEPOIS do fork — prova que a comparação usa merge-base
    (three-dot), não `main..feature` (two-dot), que incluiria esse commit."""
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    (repo / "feature.txt").write_text("feature content\n")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-q", "-m", "feature commit"], repo)
    (repo / "file.txt").write_text("edited on feature\n")
    (repo / "untracked.txt").write_text("wip\n")

    _run(["git", "checkout", "-q", "main"], repo)
    (repo / "only_on_main.txt").write_text("main-only\n")
    _run(["git", "add", "only_on_main.txt"], repo)
    _run(["git", "commit", "-q", "-m", "main moved on after fork"], repo)
    _run(["git", "checkout", "-q", "feature"], repo)
    return repo


def test_merge_base_finds_fork_point(feature_repo):
    sha = merge_base(str(feature_repo), "main")
    assert sha
    # merge-base é o commit "init" (pai comum), não o HEAD atual de main.
    main_head = subprocess.run(
        ["git", "rev-parse", "main"], cwd=feature_repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert sha != main_head


def test_merge_base_nonexistent_ref(repo):
    assert merge_base(str(repo), "does-not-exist") == ""


def test_get_compare_scan_lists_feature_changes_not_main(feature_repo):
    scan = get_compare_scan(str(feature_repo), "main")
    assert not scan.error
    assert scan.merge_base_sha
    paths = {f.path for f in scan.files}
    assert "feature.txt" in paths        # commitado na feature
    assert "file.txt" in paths           # editado não-commitado
    assert "untracked.txt" in paths      # untracked
    assert "only_on_main.txt" not in paths  # só existe no commit extra de main


def test_get_compare_scan_untracked_status(feature_repo):
    scan = get_compare_scan(str(feature_repo), "main")
    untracked = {f.path: f.status for f in scan.files}["untracked.txt"]
    assert untracked == "??"


def test_get_compare_scan_base_inexistente(repo):
    scan = get_compare_scan(str(repo), "nao-existe-em-lugar-nenhum")
    assert scan.error
    assert scan.files == []


def test_get_compare_scan_numstat(feature_repo):
    scan = get_compare_scan(str(feature_repo), "main")
    added, removed = scan.numstat.get("feature.txt", (0, 0))
    assert added >= 1


def test_get_diff_range_committed_and_edited(feature_repo):
    scan = get_compare_scan(str(feature_repo), "main")
    text = get_diff_range(str(feature_repo), "file.txt", scan.merge_base_sha)
    assert "edited on feature" in text


def test_get_diff_range_untracked(feature_repo):
    scan = get_compare_scan(str(feature_repo), "main")
    text = get_diff_range(str(feature_repo), "untracked.txt", scan.merge_base_sha)
    assert "wip" in text


def test_get_diff_range_size_cap(feature_repo, monkeypatch):
    from claude_workspaces import git_status as gs
    monkeypatch.setattr(gs, "MAX_DIFF_BYTES", 4)
    scan = get_compare_scan(str(feature_repo), "main")
    text = get_diff_range(str(feature_repo), "feature.txt", scan.merge_base_sha)
    assert text.startswith("(diff grande demais")
