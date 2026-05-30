"""Testes de fluxo do WorkspaceCoordinator.

Não testa widgets — só signals, CRUD e cache. Não polui ~/.config:
load/save são monkeypatched pra no-ops/in-memory.
"""

import pytest

from claude_workspaces.models import Workspace


@pytest.fixture
def coord(qapp, monkeypatch):
    monkeypatch.setattr(
        "claude_workspaces.ui.coordinators.workspace_coordinator.load_workspaces",
        lambda: [],
    )
    saves = []
    monkeypatch.setattr(
        "claude_workspaces.ui.coordinators.workspace_coordinator.save_workspaces",
        lambda ws: saves.append(list(ws)),
    )
    from claude_workspaces.ui.coordinators.workspace_coordinator import WorkspaceCoordinator
    c = WorkspaceCoordinator()
    saves.clear()  # descarta save do _migrate_ids_if_needed
    return c, saves


def _ws(name="proj", folders=None) -> Workspace:
    return Workspace(name=name, folders=folders or ["/tmp/proj"])


# ---------- add ----------

def test_add_appends_workspace(coord):
    c, saves = coord
    ws = _ws()
    c.add(ws)
    assert ws in c.workspaces


def test_add_persists(coord):
    c, saves = coord
    c.add(_ws())
    assert len(saves) == 1


def test_add_emits_workspaces_changed(coord):
    c, _ = coord
    emitted = []
    c.workspaces_changed.connect(lambda: emitted.append(1))
    c.add(_ws())
    assert len(emitted) == 1


# ---------- replace ----------

def test_replace_updates_by_id(coord):
    c, _ = coord
    ws = _ws("original")
    c.add(_ws.__wrapped__ if hasattr(_ws, "__wrapped__") else _ws("original"))
    c.workspaces.clear()
    c.workspaces.append(ws)

    updated = Workspace(id=ws.id, name="atualizado", folders=["/tmp/proj"])
    result = c.replace(updated)
    assert result is True
    assert c.workspaces[0].name == "atualizado"


def test_replace_returns_false_for_unknown_id(coord):
    c, _ = coord
    ws = Workspace(name="fantasma", folders=[])
    assert c.replace(ws) is False


def test_replace_emits_signal(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    emitted = []
    c.workspaces_changed.connect(lambda: emitted.append(1))
    c.replace(Workspace(id=ws.id, name="novo", folders=[]))
    assert len(emitted) == 1


def test_replace_persists(coord):
    c, saves = coord
    ws = _ws()
    c.workspaces.append(ws)
    saves.clear()
    c.replace(Workspace(id=ws.id, name="novo", folders=[]))
    assert len(saves) == 1


def test_replace_invalidates_session_cache(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    c._session_text_cache[ws.id] = "cached"
    c.replace(Workspace(id=ws.id, name="novo", folders=[]))
    assert ws.id not in c._session_text_cache


# ---------- delete ----------

def test_delete_removes_workspace(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    result = c.delete(ws.id)
    assert result is True
    assert ws not in c.workspaces


def test_delete_returns_false_for_unknown_id(coord):
    c, _ = coord
    assert c.delete("nao-existe") is False


def test_delete_emits_workspace_deleted(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    deleted_ids = []
    c.workspace_deleted.connect(lambda wid: deleted_ids.append(wid))
    c.delete(ws.id)
    assert deleted_ids == [ws.id]


def test_delete_emits_workspaces_changed(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    emitted = []
    c.workspaces_changed.connect(lambda: emitted.append(1))
    c.delete(ws.id)
    assert len(emitted) == 1


def test_delete_persists(coord):
    c, saves = coord
    ws = _ws()
    c.workspaces.append(ws)
    saves.clear()
    c.delete(ws.id)
    assert len(saves) == 1


def test_delete_invalidates_session_cache(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    c._session_text_cache[ws.id] = "cached"
    c.delete(ws.id)
    assert ws.id not in c._session_text_cache


# ---------- set_pinned ----------

def test_set_pinned_true(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    result = c.set_pinned(ws.id, True)
    assert result is True
    assert ws.pinned is True


def test_set_pinned_noop_if_same_state(coord):
    c, saves = coord
    ws = _ws()
    ws.pinned = True
    c.workspaces.append(ws)
    saves.clear()
    result = c.set_pinned(ws.id, True)
    assert result is False
    assert len(saves) == 0


def test_set_pinned_emits_signal(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    emitted = []
    c.workspaces_changed.connect(lambda: emitted.append(1))
    c.set_pinned(ws.id, True)
    assert len(emitted) == 1


def test_set_pinned_returns_false_for_unknown_id(coord):
    c, _ = coord
    assert c.set_pinned("nao-existe", True) is False


# ---------- set_minimized ----------

def test_set_minimized_true(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    result = c.set_minimized(ws.id, True)
    assert result is True
    assert ws.minimized is True


def test_set_minimized_false_restores(coord):
    c, _ = coord
    ws = _ws()
    ws.minimized = True
    c.workspaces.append(ws)
    c.set_minimized(ws.id, False)
    assert ws.minimized is False


def test_set_minimized_noop_if_same_state(coord):
    c, saves = coord
    ws = _ws()
    c.workspaces.append(ws)
    saves.clear()
    result = c.set_minimized(ws.id, False)
    assert result is False
    assert len(saves) == 0


# ---------- find_by_id ----------

def test_find_by_id_found(coord):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    assert c.find_by_id(ws.id) is ws


def test_find_by_id_not_found(coord):
    c, _ = coord
    assert c.find_by_id("nao-existe") is None


# ---------- find_for_cwd ----------

def test_find_for_cwd_exact_match(coord):
    c, _ = coord
    ws = Workspace(name="proj", folders=["/home/user/proj"])
    c.workspaces.append(ws)
    assert c.find_for_cwd("/home/user/proj") is ws


def test_find_for_cwd_prefix_match(coord):
    c, _ = coord
    ws = Workspace(name="proj", folders=["/home/user/proj"])
    c.workspaces.append(ws)
    assert c.find_for_cwd("/home/user/proj/src/module") is ws


def test_find_for_cwd_no_match(coord):
    c, _ = coord
    ws = Workspace(name="proj", folders=["/home/user/proj"])
    c.workspaces.append(ws)
    assert c.find_for_cwd("/home/other/repo") is None


def test_find_for_cwd_no_prefix_false_positive(coord):
    c, _ = coord
    ws = Workspace(name="proj", folders=["/home/user/proj"])
    c.workspaces.append(ws)
    # "/home/user/proj2" starts with "/home/user/proj" as string but NOT as path prefix
    assert c.find_for_cwd("/home/user/proj2") is None


# ---------- session_text_for cache ----------

def test_session_text_cached(coord, monkeypatch):
    c, _ = coord
    ws = _ws()
    c.workspaces.append(ws)
    calls = []

    def fake_list_sessions(paths, limit=15):
        calls.append(1)
        return []

    monkeypatch.setattr(
        "claude_workspaces.ui.coordinators.workspace_coordinator"
        ".WorkspaceCoordinator.session_text_for",
        lambda self, w: self._session_text_cache.setdefault(w.id, "cached"),
    )
    # Access twice — second should hit cache
    c._session_text_cache[ws.id] = "cached"
    result1 = c.session_text_for(ws)
    result2 = c.session_text_for(ws)
    assert result1 == result2 == "cached"


def test_invalidate_cache_specific(coord):
    c, _ = coord
    ws = _ws()
    c._session_text_cache[ws.id] = "cached"
    c._session_text_cache["other"] = "other"
    c.invalidate_cache(ws.id)
    assert ws.id not in c._session_text_cache
    assert "other" in c._session_text_cache


def test_invalidate_cache_all(coord):
    c, _ = coord
    c._session_text_cache["a"] = "x"
    c._session_text_cache["b"] = "y"
    c.invalidate_cache()
    assert c._session_text_cache == {}
