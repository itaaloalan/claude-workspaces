"""Testes do parser de URL do GitHub e helpers do pr_provider."""

from claude_workspaces.pr_provider import GithubRemote, parse_github_remote


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
