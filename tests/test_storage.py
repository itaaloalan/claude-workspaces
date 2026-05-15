import json

import pytest

from claude_workspaces import storage
from claude_workspaces.models import Workspace


@pytest.fixture
def patched_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "config_dir", lambda: tmp_path)
    return tmp_path


def test_load_empty(patched_config_dir):
    assert storage.load_workspaces() == []


def test_save_and_load_roundtrip(patched_config_dir):
    ws1 = Workspace(
        name="alpha",
        folders=["/tmp/a"],
        description="primeiro",
    )
    ws2 = Workspace(name="beta", folders=["/tmp/b"])
    storage.save_workspaces([ws1, ws2])

    loaded = storage.load_workspaces()
    assert len(loaded) == 2
    assert loaded[0].name == "alpha"
    assert loaded[0].id == ws1.id
    assert loaded[1].name == "beta"


def test_save_creates_directory(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested"
    monkeypatch.setattr(storage, "config_dir", lambda: nested)
    storage.save_workspaces([Workspace(name="x")])
    assert (nested / "workspaces.json").exists()


def test_legacy_file_without_ids_is_readable(patched_config_dir):
    """Arquivo antigo sem campo 'id' carrega ok, ids são gerados."""
    legacy = {
        "workspaces": [
            {"name": "old", "folders": ["/x"], "description": "sem id"},
        ]
    }
    (patched_config_dir / "workspaces.json").write_text(json.dumps(legacy))
    loaded = storage.load_workspaces()
    assert len(loaded) == 1
    assert loaded[0].id  # gerado
    assert loaded[0].name == "old"
