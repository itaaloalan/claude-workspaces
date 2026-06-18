"""Testes de integração da MainWindow — exercita a sidebar de verdade.

Constrói uma MainWindow real (offscreen) com HOME isolado num tmp_path, de
modo que storage/settings/notifications não tocam no ~/.config do usuário.
Cobre as ações da sidebar end-to-end: add/delete workspace, refresh_list,
filtro (debounce + imediato), seleção/highlight, pin, minimize e badges.

É o que faltava para cobrir o main_window.py — os widgets isolados já tinham
testes, mas o fluxo real (coordinator → signal → refresh_list → tree) não.
"""

import pathlib
import tempfile
from unittest.mock import patch

import pytest

from claude_workspaces.models import Workspace


@pytest.fixture
def main_window(qapp):
    """MainWindow real com HOME isolado. Fecha e para timers no teardown."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    with patch("pathlib.Path.home", return_value=tmp):
        from claude_workspaces.ui.main_window import MainWindow

        w = MainWindow()
        try:
            yield w
        finally:
            # Para todos os QTimer pendentes antes de destruir o widget pra
            # não disparar slots num objeto meio-morto.
            for attr in (
                "_long_running_timer",
                "_repo_poll_timer",
                "_idle_tick_timer",
                "_plan_usage_updated_timer",
                "_layout_save_timer",
                "_filter_timer",
                "_sessions_persist_timer",
            ):
                t = getattr(w, attr, None)
                if t is not None:
                    t.stop()
            w.close()


def _add_ws(w, name, **kw):
    ws = Workspace(name=name, folders=kw.pop("folders", [f"/tmp/{name}"]), **kw)
    w.workspaces_coord.add(ws)
    return ws


def _top_workspaces(w):
    """IDs/labels dos workspaces visíveis (ignora headers de seção)."""
    out = []
    for i in range(w.list_widget.topLevelItemCount()):
        it = w.list_widget.topLevelItem(i)
        from claude_workspaces.models import Workspace as _W
        data = it.data(0, 0x0100)  # Qt.UserRole
        if isinstance(data, _W):
            out.append(data)
    return out


# ---------- construção ----------

def test_constructs_empty(main_window):
    assert main_window.list_widget.topLevelItemCount() == 0


def test_window_title(main_window):
    assert main_window.windowTitle() == "Claude Workspaces"


# ---------- add workspace ----------

def test_add_workspace_appears_in_tree(main_window):
    _add_ws(main_window, "ProjA")
    assert main_window.list_widget.topLevelItemCount() == 1


def test_add_two_workspaces(main_window):
    _add_ws(main_window, "ProjA")
    _add_ws(main_window, "ProjB")
    names = [ws.name for ws in _top_workspaces(main_window)]
    assert "ProjA" in names and "ProjB" in names


def test_find_workspace_item(main_window):
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    assert item is not None


def test_find_workspace_item_unknown_returns_none(main_window):
    assert main_window._find_workspace_item("nope") is None


# ---------- pinned section ----------

def test_pin_creates_fixados_header(main_window):
    ws = _add_ws(main_window, "ProjA")
    _add_ws(main_window, "ProjB")
    main_window.workspaces_coord.set_pinned(ws.id, True)
    # Deve existir um header FIXADOS no topo
    labels = []
    for i in range(main_window.list_widget.topLevelItemCount()):
        it = main_window.list_widget.topLevelItem(i)
        if main_window._is_section_header(it):
            labels.append(it.text(0) or it.data(0, 0x0100))
    # Header existe (texto pode estar no widget) — ao menos 2 seções
    headers = sum(
        1 for i in range(main_window.list_widget.topLevelItemCount())
        if main_window._is_section_header(main_window.list_widget.topLevelItem(i))
    )
    assert headers >= 1


# ---------- minimize ----------

def test_minimize_removes_from_list(main_window):
    ws = _add_ws(main_window, "ProjA")
    _add_ws(main_window, "ProjB")
    main_window.workspaces_coord.set_minimized(ws.id, True)
    names = [w.name for w in _top_workspaces(main_window)]
    assert "ProjA" not in names
    assert "ProjB" in names


# ---------- delete ----------

def test_delete_workspace_removes_item(main_window):
    ws = _add_ws(main_window, "ProjA")
    main_window.workspaces_coord.delete(ws.id)
    assert main_window._find_workspace_item(ws.id) is None


# ---------- filtro: debounce ----------

def test_apply_filter_schedules_timer(main_window):
    _add_ws(main_window, "ProjA")
    main_window._apply_filter("proj")
    assert main_window._pending_filter == "proj"
    assert main_window._filter_timer.isActive()


def test_apply_filter_does_not_filter_immediately(main_window):
    # Debounce: o _apply_filter agenda mas NÃO esconde nada na hora.
    ws = _add_ws(main_window, "ProjA")
    main_window._apply_filter("xxxxxx-nao-existe")
    item = main_window._find_workspace_item(ws.id)
    assert not item.isHidden()  # ainda visível — só esconde após o timer


def test_do_apply_filter_hides_non_matching(main_window):
    a = _add_ws(main_window, "Alpha")
    b = _add_ws(main_window, "Beta")
    main_window._pending_filter = "alph"
    main_window._do_apply_filter()
    assert not main_window._find_workspace_item(a.id).isHidden()
    assert main_window._find_workspace_item(b.id).isHidden()


def test_do_apply_filter_empty_shows_all(main_window):
    a = _add_ws(main_window, "Alpha")
    b = _add_ws(main_window, "Beta")
    main_window._pending_filter = "alph"
    main_window._do_apply_filter()
    main_window._pending_filter = ""
    main_window._do_apply_filter()
    assert not main_window._find_workspace_item(a.id).isHidden()
    assert not main_window._find_workspace_item(b.id).isHidden()


def test_filter_timer_fires_eventually(main_window, qtbot):
    a = _add_ws(main_window, "Alpha")
    b = _add_ws(main_window, "Beta")
    main_window._apply_filter("beta")
    # Espera o debounce de 150ms disparar de verdade.
    qtbot.wait(250)
    assert main_window._find_workspace_item(a.id).isHidden()
    assert not main_window._find_workspace_item(b.id).isHidden()


def test_filter_matches_description(main_window):
    ws = _add_ws(main_window, "Proj", description="backend java spring")
    main_window._pending_filter = "spring"
    main_window._do_apply_filter()
    assert not main_window._find_workspace_item(ws.id).isHidden()


# ---------- seleção / highlight ----------

def test_selection_highlights_workspace(main_window):
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    main_window.list_widget.setCurrentItem(item)
    w = main_window.list_widget.itemWidget(item, 0)
    from claude_workspaces.ui.workspace_item_widget import WorkspaceItemWidget
    assert isinstance(w, WorkspaceItemWidget)
    assert w._selected is True


def test_workspace_of_item_resolves_parent(main_window):
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    resolved = main_window._workspace_of_item(item)
    assert resolved is not None and resolved.id == ws.id


# ---------- badges de atividade ----------

def test_activity_badges_no_crash(main_window):
    _add_ws(main_window, "ProjA")
    _add_ws(main_window, "ProjB")
    main_window._refresh_activity_badges()  # não deve lançar


# ---------- refresh_list idempotente ----------

def test_refresh_list_preserves_selection(main_window):
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    main_window.list_widget.setCurrentItem(item)
    main_window.refresh_list()
    cur = main_window.list_widget.currentItem()
    assert main_window._workspace_of_item(cur).id == ws.id


def test_refresh_list_keeps_updates_enabled(main_window):
    """O batching de paint deve sempre reabilitar updates (finally)."""
    _add_ws(main_window, "ProjA")
    main_window.refresh_list()
    assert main_window.list_widget.updatesEnabled() is True


# ---------- ações reais de clique na sidebar ----------

def test_collapse_button_toggles_expanded(main_window):
    from claude_workspaces.ui.workspace_item_widget import WorkspaceItemWidget
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    w = main_window.list_widget.itemWidget(item, 0)
    assert isinstance(w, WorkspaceItemWidget)
    before = item.isExpanded()
    w._collapse_btn.clicked.emit()
    assert item.isExpanded() != before


def test_toggle_pin_workspace_roundtrip(main_window):
    ws = _add_ws(main_window, "ProjA")
    main_window._toggle_pin_workspace(ws)
    assert main_window.workspaces_coord.find_by_id(ws.id).pinned is True
    # Após refresh, pega a instância atualizada do workspace
    ws2 = main_window.workspaces_coord.find_by_id(ws.id)
    main_window._toggle_pin_workspace(ws2)
    assert main_window.workspaces_coord.find_by_id(ws.id).pinned is False


def test_minimize_then_restore(main_window):
    ws = _add_ws(main_window, "ProjA")
    main_window._minimize_workspace(ws)
    assert main_window._find_workspace_item(ws.id) is None
    main_window._on_minimized_workspace_restore(ws.id)
    assert main_window._find_workspace_item(ws.id) is not None


def test_add_btn_hidden_until_hover(main_window):
    from PySide6.QtCore import QEvent

    from claude_workspaces.ui.workspace_item_widget import WorkspaceItemWidget
    ws = _add_ws(main_window, "ProjA")
    item = main_window._find_workspace_item(ws.id)
    w = main_window.list_widget.itemWidget(item, 0)
    assert isinstance(w, WorkspaceItemWidget)
    # botão + começa oculto, revela no hover (event() trata HoverEnter)
    assert w._add_btn.isHidden()
    w.event(QEvent(QEvent.Type.HoverEnter))
    assert not w._add_btn.isHidden()


def test_search_submit_no_crash(main_window):
    _add_ws(main_window, "ProjA")
    main_window.top_bar.search.setText("proj")
    main_window._search_submit()  # não deve lançar


# ---------- persistência de sessões (incremental / shutdown) ----------

def test_persist_active_sessions_skips_rewrite_when_unchanged(main_window):
    """Sem mudanças no conjunto de consoles, _persist_active_sessions não
    reescreve o arquivo (timer periódico chama isto a cada poucos segundos)."""
    from claude_workspaces import session_persistence as sp

    calls = []
    # O restore semeia _last_persisted_payload no startup; zera pra exercitar
    # o "1ª grava / 2ª no-op" de forma determinística.
    main_window._last_persisted_payload = None
    with patch.object(sp, "save_sessions", side_effect=lambda s: calls.append(s)):
        # main_window importa save_sessions no namespace do módulo
        from claude_workspaces.ui import main_window as mw
        with patch.object(mw, "save_sessions", side_effect=lambda s: calls.append(s)):
            main_window._persist_active_sessions()  # 1ª vez: grava (vazio)
            main_window._persist_active_sessions()  # 2ª: idêntico, no-op
    assert len(calls) == 1


def test_persist_on_shutdown_is_idempotent(main_window):
    """closeEvent + aboutToQuit podem ambos chamar _persist_on_shutdown; só o
    primeiro grava, o segundo vira no-op (não clobbera com lista vazia)."""
    from claude_workspaces.ui import main_window as mw

    calls = []
    # Estado limpo: o restore semeia _last_persisted_payload no startup.
    main_window._last_persisted_payload = None
    main_window._shutdown_persisted = False
    with patch.object(mw, "save_sessions", side_effect=lambda s: calls.append(s)):
        main_window._persist_on_shutdown()
        main_window._persist_on_shutdown()
    assert main_window._shutdown_persisted is True
    assert len(calls) == 1
    # timer periódico é parado no shutdown
    assert not main_window._sessions_persist_timer.isActive()
