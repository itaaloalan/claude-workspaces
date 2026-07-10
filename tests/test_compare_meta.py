"""Testes do compare_meta — última base de comparação persistida por repo."""

import pytest

from claude_workspaces import compare_meta


@pytest.fixture
def patched_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(compare_meta, "config_dir", lambda: tmp_path)
    return tmp_path


def test_get_unknown_returns_empty(patched_config_dir):
    assert compare_meta.get_compare_base("/qualquer/repo") == ""


def test_set_and_get_roundtrip(patched_config_dir, tmp_path):
    repo = tmp_path / "repo.claude" / "feat_x"
    repo.mkdir(parents=True)
    compare_meta.set_compare_base(str(repo), "origin/dev")
    assert compare_meta.get_compare_base(str(repo)) == "origin/dev"
    # Persistido em disco.
    assert (tmp_path / "compare_bases.json").exists()


def test_set_empty_base_is_noop(patched_config_dir, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    compare_meta.set_compare_base(str(repo), "")
    compare_meta.set_compare_base(str(repo), "   ")
    assert compare_meta.get_compare_base(str(repo)) == ""
    assert not (tmp_path / "compare_bases.json").exists()


def test_path_normalization_same_key(patched_config_dir, tmp_path):
    # Path com componentes redundantes resolve pra mesma chave.
    repo = tmp_path / "repo.claude" / "feat_y"
    repo.mkdir(parents=True)
    compare_meta.set_compare_base(str(repo), "main")
    weird = str(tmp_path / "repo.claude" / "." / "feat_y")
    assert compare_meta.get_compare_base(weird) == "main"


def test_forget_removes_entry(patched_config_dir, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    compare_meta.set_compare_base(str(repo), "dev")
    compare_meta.forget_compare_base(str(repo))
    assert compare_meta.get_compare_base(str(repo)) == ""


def test_load_returns_empty_on_corrupt_json(patched_config_dir, tmp_path):
    (tmp_path / "compare_bases.json").write_text("{ not json", encoding="utf-8")
    assert compare_meta.get_compare_base("/x") == ""
