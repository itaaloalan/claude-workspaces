"""Testes do worktree_meta — base branch persistida por worktree."""

import pytest

from claude_workspaces import worktree_meta


@pytest.fixture
def patched_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(worktree_meta, "config_dir", lambda: tmp_path)
    return tmp_path


def test_get_unknown_returns_empty(patched_config_dir):
    assert worktree_meta.get_base_branch("/qualquer/wt") == ""


def test_set_and_get_roundtrip(patched_config_dir, tmp_path):
    wt = tmp_path / "repo.claude" / "feat_x"
    wt.mkdir(parents=True)
    worktree_meta.set_base_branch(str(wt), "dev")
    assert worktree_meta.get_base_branch(str(wt)) == "dev"
    # Persistido em disco.
    assert (tmp_path / "worktree_bases.json").exists()


def test_set_empty_base_is_noop(patched_config_dir, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    worktree_meta.set_base_branch(str(wt), "")
    worktree_meta.set_base_branch(str(wt), "   ")
    assert worktree_meta.get_base_branch(str(wt)) == ""
    assert not (tmp_path / "worktree_bases.json").exists()


def test_path_normalization_same_key(patched_config_dir, tmp_path):
    # Path com componentes redundantes resolve pra mesma chave.
    wt = tmp_path / "repo.claude" / "feat_y"
    wt.mkdir(parents=True)
    worktree_meta.set_base_branch(str(wt), "main")
    weird = str(tmp_path / "repo.claude" / "." / "feat_y")
    assert worktree_meta.get_base_branch(weird) == "main"


def test_forget_removes_entry(patched_config_dir, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    worktree_meta.set_base_branch(str(wt), "dev")
    worktree_meta.forget_base_branch(str(wt))
    assert worktree_meta.get_base_branch(str(wt)) == ""


def test_load_returns_empty_on_corrupt_json(patched_config_dir, tmp_path):
    (tmp_path / "worktree_bases.json").write_text("{ not json", encoding="utf-8")
    assert worktree_meta.get_base_branch("/x") == ""
