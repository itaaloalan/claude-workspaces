import os
import tempfile

import pytest

from claude_workspaces.models import Task, Workspace


def test_workspace_default_id_unique():
    a = Workspace(name="a")
    b = Workspace(name="b")
    assert a.id and b.id
    assert a.id != b.id


def test_task_default_id_unique():
    t1 = Task(title="x")
    t2 = Task(title="y")
    assert t1.id and t2.id
    assert t1.id != t2.id
    assert t1.done is False
    assert t1.created_at


def test_workspace_roundtrip():
    ws = Workspace(
        name="proj",
        folders=["/a", "/b"],
        description="hello",
        tasks=[Task(title="fix bug", done=True), Task(title="ship")],
    )
    d = ws.to_dict()
    back = Workspace.from_dict(d)
    assert back.name == "proj"
    assert back.folders == ["/a", "/b"]
    assert back.description == "hello"
    assert back.id == ws.id
    assert len(back.tasks) == 2
    assert back.tasks[0].title == "fix bug"
    assert back.tasks[0].done is True
    assert back.tasks[1].title == "ship"
    assert back.tasks[1].done is False


def test_workspace_from_dict_fills_missing_id():
    """Compatibilidade com workspaces.json antigo, sem id."""
    legacy = {"name": "p", "folders": ["/a"], "description": ""}
    ws = Workspace.from_dict(legacy)
    assert ws.id
    assert ws.name == "p"


def test_launch_paths_single_folder():
    ws = Workspace(name="x", folders=["/tmp/single"])
    cwd, extras = ws.launch_paths()
    assert cwd == "/tmp/single"
    assert extras == []


def test_launch_paths_siblings_uses_parent():
    """Pastas-irmãs sob o mesmo pai → cwd é o pai, sem --add-dir."""
    with tempfile.TemporaryDirectory() as root:
        a = os.path.join(root, "a")
        b = os.path.join(root, "b")
        os.makedirs(a)
        os.makedirs(b)
        ws = Workspace(name="x", folders=[a, b])
        cwd, extras = ws.launch_paths()
        assert cwd == root
        assert extras == []


def test_launch_paths_unrelated_uses_first_plus_extras():
    ws = Workspace(name="x", folders=["/tmp/unrelated-x", "/var/log"])
    cwd, extras = ws.launch_paths()
    assert cwd == "/tmp/unrelated-x"
    assert extras == ["/var/log"]


def test_launch_paths_empty_raises():
    ws = Workspace(name="x", folders=[])
    with pytest.raises(ValueError):
        ws.launch_paths()
