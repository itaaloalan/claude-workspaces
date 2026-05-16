import os
import tempfile

import pytest

from claude_workspaces.models import Workspace


def test_workspace_default_id_unique():
    a = Workspace(name="a")
    b = Workspace(name="b")
    assert a.id and b.id
    assert a.id != b.id


def test_workspace_roundtrip():
    ws = Workspace(
        name="proj",
        folders=["/a", "/b"],
        description="hello",
    )
    d = ws.to_dict()
    back = Workspace.from_dict(d)
    assert back.name == "proj"
    assert back.folders == ["/a", "/b"]
    assert back.description == "hello"
    assert back.id == ws.id


def test_workspace_from_dict_fills_missing_id():
    """Compatibilidade com workspaces.json antigo, sem id."""
    legacy = {"name": "p", "folders": ["/a"], "description": ""}
    ws = Workspace.from_dict(legacy)
    assert ws.id
    assert ws.name == "p"


def test_workspace_overrides_default_to_none():
    """Workspace antigo (sem campos de override) carrega com None/vazio."""
    ws = Workspace.from_dict({"name": "p", "folders": ["/a"]})
    assert ws.branch_prefix == ""
    assert ws.default_isolate_worktree is None
    assert ws.default_create_new_branch is None


def test_workspace_overrides_roundtrip():
    ws = Workspace(
        name="p",
        folders=["/a"],
        branch_prefix="italo",
        default_isolate_worktree=True,
        default_create_new_branch=False,
    )
    back = Workspace.from_dict(ws.to_dict())
    assert back.branch_prefix == "italo"
    assert back.default_isolate_worktree is True
    assert back.default_create_new_branch is False


def test_workspace_overrides_corrupt_bool_becomes_none():
    """Se o JSON tem string ou número onde devia ter bool, vira None
    (em vez de quebrar a desserialização)."""
    ws = Workspace.from_dict({
        "name": "p",
        "folders": ["/a"],
        "default_isolate_worktree": "yes",  # tipo errado
        "default_create_new_branch": 1,     # tipo errado
    })
    assert ws.default_isolate_worktree is None
    assert ws.default_create_new_branch is None


def test_workspace_from_dict_ignores_legacy_tasks():
    """Workspaces antigos com chave 'tasks' devem ser carregados sem erro."""
    legacy = {"name": "p", "folders": ["/a"], "tasks": [{"id": "x", "title": "old"}]}
    ws = Workspace.from_dict(legacy)
    assert ws.name == "p"
    assert not hasattr(ws, "tasks")


def test_launch_paths_single_folder():
    ws = Workspace(name="x", folders=["/tmp/single"])
    cwd, extras = ws.launch_paths()
    assert cwd == "/tmp/single"
    assert extras == []


def test_launch_paths_siblings_no_parent_collapse():
    """Pastas-irmãs sob o mesmo pai NÃO devem colapsar pro pai — o Claude
    veria o pai inteiro (incluindo irmãos não-listados) e vazaria contexto.
    Sempre: primeira pasta como cwd, demais via --add-dir.
    """
    with tempfile.TemporaryDirectory() as root:
        a = os.path.join(root, "a")
        b = os.path.join(root, "b")
        os.makedirs(a)
        os.makedirs(b)
        ws = Workspace(name="x", folders=[a, b])
        cwd, extras = ws.launch_paths()
        assert cwd == a
        assert extras == [b]


def test_launch_paths_unrelated_uses_first_plus_extras():
    ws = Workspace(name="x", folders=["/tmp/unrelated-x", "/var/log"])
    cwd, extras = ws.launch_paths()
    assert cwd == "/tmp/unrelated-x"
    assert extras == ["/var/log"]


def test_launch_paths_empty_raises():
    ws = Workspace(name="x", folders=[])
    with pytest.raises(ValueError):
        ws.launch_paths()
