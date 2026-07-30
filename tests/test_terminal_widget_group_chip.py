"""Regressão: chip 🌿 da sidebar não aparecia pra sessões abertas na
pasta-pai de um grupo de worktrees (ex.: `.worktrees/<nome>/` contendo
`map-api/` e `map-web/`, cada um um worktree linkado, mas a própria
pasta-pai sem `.git`). set_context_info agora guarda o 1º membro do
grupo em `group_chip_dir()`, que main_window usa como alvo alternativo
do git status pro chip (ver `_on_repo_status_ready`)."""

import subprocess

import pytest

from claude_workspaces.git_worktree import add_worktree
from claude_workspaces.ui.terminal_widget import TerminalWidget


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo_path)
    _run(["git", "config", "user.email", "t@t"], repo_path)
    _run(["git", "config", "user.name", "t"], repo_path)
    (repo_path / "f.txt").write_text("hi\n")
    _run(["git", "add", "f.txt"], repo_path)
    _run(["git", "commit", "-q", "-m", "init"], repo_path)
    return repo_path


@pytest.fixture
def widget(qapp, tmp_workspaces):
    return TerminalWidget()


def test_group_chip_dir_set_for_worktree_group(widget, repo, tmp_path):
    """cwd pasta-grupo (sem .git) + extras com worktrees-membros → primeiro
    extra vira o alvo do chip."""
    ok, _msg, wt = add_worktree(str(repo), "feat/x")
    assert ok
    group_parent = tmp_path / "group"
    group_parent.mkdir()

    widget.set_context_info(
        str(group_parent), [str(wt)], worktree_label=" · feat/x", is_worktree=True
    )
    assert widget.group_chip_dir() == str(wt)


def test_group_chip_dir_empty_for_single_worktree(widget, repo):
    """cwd que já É o worktree (não pasta-grupo) não deve preencher
    group_chip_dir — o chip usa worktree_dir() normalmente nesse caso."""
    ok, _msg, wt = add_worktree(str(repo), "feat/y")
    assert ok

    widget.set_context_info(str(wt), [], worktree_label=" · feat/y", is_worktree=True)
    assert widget.group_chip_dir() == ""


def test_group_chip_dir_empty_when_not_worktree(widget, repo):
    """Pasta comum (is_worktree=False) nunca preenche group_chip_dir, mesmo
    com extras."""
    widget.set_context_info(str(repo), ["/algum/extra"], is_worktree=False)
    assert widget.group_chip_dir() == ""
