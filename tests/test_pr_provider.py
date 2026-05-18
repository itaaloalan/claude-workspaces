"""Testes do parser de URL do GitHub e helpers do pr_provider."""

import subprocess

import pytest

from claude_workspaces import pr_provider
from claude_workspaces.pr_provider import GithubRemote, parse_github_remote


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def test_parse_https_com_git():
    r = parse_github_remote("https://github.com/owner/repo.git")
    assert r == GithubRemote(owner="owner", repo="repo")
    assert r.full_name == "owner/repo"


def test_parse_https_sem_git():
    r = parse_github_remote("https://github.com/owner/repo")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_https_trailing_slash():
    r = parse_github_remote("https://github.com/owner/repo/")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_https_com_token():
    r = parse_github_remote("https://x-access-token:abc@github.com/owner/repo.git")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_ssh_classico():
    r = parse_github_remote("git@github.com:owner/repo.git")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_ssh_sem_git():
    r = parse_github_remote("git@github.com:owner/repo")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_ssh_url_form():
    r = parse_github_remote("ssh://git@github.com/owner/repo.git")
    assert r == GithubRemote(owner="owner", repo="repo")


def test_parse_owner_com_traco_ponto():
    r = parse_github_remote("https://github.com/my-org.io/my.repo.git")
    assert r is not None
    assert r.owner == "my-org.io"
    assert r.repo == "my.repo"


def test_parse_nao_github():
    assert parse_github_remote("https://gitlab.com/owner/repo.git") is None
    assert parse_github_remote("https://bitbucket.org/owner/repo.git") is None


def test_parse_vazio_ou_invalido():
    assert parse_github_remote("") is None
    assert parse_github_remote("   ") is None
    assert parse_github_remote("not a url") is None
    assert parse_github_remote("https://github.com/") is None
    assert parse_github_remote("https://github.com/owner") is None


def test_parse_strip_whitespace():
    r = parse_github_remote("  https://github.com/owner/repo.git  ")
    assert r == GithubRemote(owner="owner", repo="repo")


# ---------- _run_git: tolerância a falhas no subprocess --------------------


def test_run_git_missing_returns_negative_rc(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(pr_provider.subprocess, "run", boom)
    rc, out = pr_provider._run_git(["status"], "/tmp")
    assert rc == -1
    assert "git" in out


def test_run_git_timeout_returns_negative_rc(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)
    monkeypatch.setattr(pr_provider.subprocess, "run", boom)
    rc, _out = pr_provider._run_git(["status"], "/tmp")
    assert rc == -1


# ---------- helpers contra repo git real ---------------------------------


@pytest.fixture
def repo(tmp_path):
    _run(["git", "init", "-q", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "t@t"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("hi\n")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-q", "-m", "init"], tmp_path)
    return tmp_path


def test_get_remote_url_sem_remote(repo):
    assert pr_provider.get_remote_url(str(repo)) == ""


def test_get_remote_url_com_remote(repo):
    _run(
        ["git", "remote", "add", "origin", "https://github.com/foo/bar.git"],
        repo,
    )
    assert (
        pr_provider.get_remote_url(str(repo))
        == "https://github.com/foo/bar.git"
    )


def test_detect_github_com_remote_github(repo):
    _run(["git", "remote", "add", "origin", "git@github.com:foo/bar.git"], repo)
    r = pr_provider.detect_github(str(repo))
    assert r is not None and r.full_name == "foo/bar"


def test_detect_github_com_remote_gitlab(repo):
    _run(
        ["git", "remote", "add", "origin", "https://gitlab.com/foo/bar.git"],
        repo,
    )
    assert pr_provider.detect_github(str(repo)) is None


def test_detect_github_sem_remote(repo):
    assert pr_provider.detect_github(str(repo)) is None


def test_current_branch_main(repo):
    assert pr_provider.current_branch(str(repo)) == "main"


def test_current_branch_detached(repo):
    _run(["git", "checkout", "--detach", "-q", "HEAD"], repo)
    assert pr_provider.current_branch(str(repo)) == ""


def test_current_branch_nao_repo(tmp_path):
    assert pr_provider.current_branch(str(tmp_path)) == ""


def test_detect_base_branch_main(repo):
    assert pr_provider.detect_base_branch(str(repo)) == "main"


def test_detect_base_branch_master(tmp_path):
    _run(["git", "init", "-q", "-b", "master"], tmp_path)
    _run(["git", "config", "user.email", "t@t"], tmp_path)
    _run(["git", "config", "user.name", "t"], tmp_path)
    (tmp_path / "f.txt").write_text("x")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-q", "-m", "init"], tmp_path)
    assert pr_provider.detect_base_branch(str(tmp_path)) == "master"


def test_detect_base_branch_fallback_main_sem_commits(tmp_path):
    _run(["git", "init", "-q", "-b", "weird"], tmp_path)
    # Sem commits → nem main nem master existem → cai no fallback
    assert pr_provider.detect_base_branch(str(tmp_path)) == "main"


def test_has_upstream_false(repo):
    assert pr_provider.has_upstream(str(repo)) is False


def test_is_dirty_clean(repo):
    assert pr_provider.is_dirty(str(repo)) is False


def test_is_dirty_com_modificacao(repo):
    (repo / "f.txt").write_text("changed\n")
    assert pr_provider.is_dirty(str(repo)) is True


def test_is_dirty_com_untracked(repo):
    (repo / "novo.txt").write_text("x")
    assert pr_provider.is_dirty(str(repo)) is True


def test_ahead_behind_mesmo_branch(repo):
    assert pr_provider.ahead_behind(str(repo), "main") == (0, 0)


def test_ahead_behind_com_commits(repo):
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    (repo / "f.txt").write_text("v2\n")
    _run(["git", "commit", "-q", "-am", "v2"], repo)
    (repo / "f.txt").write_text("v3\n")
    _run(["git", "commit", "-q", "-am", "v3"], repo)
    ahead, behind = pr_provider.ahead_behind(str(repo), "main")
    assert ahead == 2
    assert behind == 0


def test_ahead_behind_base_inexistente(repo):
    assert pr_provider.ahead_behind(str(repo), "nao-existe") == (0, 0)


# ---------- branch_state (composição) ------------------------------------


def test_branch_state_dir_inexistente():
    s = pr_provider.branch_state("/path/does/not/exist/xyz")
    assert s.error == "diretório inexistente"


def test_branch_state_folder_vazio():
    s = pr_provider.branch_state("")
    assert s.error == "diretório inexistente"


def test_branch_state_nao_repo(tmp_path):
    s = pr_provider.branch_state(str(tmp_path))
    assert s.error
    assert s.current == ""


def test_branch_state_repo_limpo(repo):
    s = pr_provider.branch_state(str(repo))
    assert s.current == "main"
    assert s.base == "main"
    assert s.has_upstream is False
    assert s.ahead == 0
    assert s.behind == 0
    assert s.dirty is False
    assert s.error == ""


def test_branch_state_dirty_e_ahead(repo):
    _run(["git", "checkout", "-q", "-b", "feature"], repo)
    (repo / "f.txt").write_text("v2\n")
    _run(["git", "commit", "-q", "-am", "v2"], repo)
    (repo / "f.txt").write_text("nao commitado\n")
    s = pr_provider.branch_state(str(repo), base="main")
    assert s.current == "feature"
    assert s.base == "main"
    assert s.ahead == 1
    assert s.dirty is True


def test_branch_state_base_explicita_nao_chama_detect(repo, monkeypatch):
    chamou = []

    def fake_detect(*a, **kw):
        chamou.append(True)
        return "outro"

    monkeypatch.setattr(pr_provider, "detect_base_branch", fake_detect)
    s = pr_provider.branch_state(str(repo), base="main")
    assert s.base == "main"
    assert not chamou
