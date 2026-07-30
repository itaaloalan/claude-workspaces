"""GlobalConsoleTabBar — mirror de consoles na top bar (estilo Orca).

Constrói MainWindow real (offscreen, HOME isolado) e verifica que a tab
bar global espelha consoles de múltiplos workspaces via sinais do
TerminalCoordinator, ativa/fecha pelo uid e mantém tooltip com o nome
do workspace.
"""

import pathlib
import tempfile
from unittest.mock import patch

import pytest

from claude_workspaces.models import Workspace


@pytest.fixture
def main_window(qapp):
    tmp = pathlib.Path(tempfile.mkdtemp())
    with patch("pathlib.Path.home", return_value=tmp):
        from claude_workspaces.ui.main_window import MainWindow

        w = MainWindow()
        try:
            yield w
        finally:
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


def _setup_consoles(w, qapp):
    ws1 = Workspace(name="alpha", folders=["/tmp/alpha"])
    ws2 = Workspace(name="beta", folders=["/tmp/beta"])
    w.workspaces_coord.add(ws1)
    w.workspaces_coord.add(ws2)
    a1 = w._get_terminal_area(ws1)
    a2 = w._get_terminal_area(ws2)
    t1 = a1.add_terminal("Console A1")
    t2 = a1.add_terminal("Console A2")
    t3 = a2.add_terminal("Console B1")
    qapp.processEvents()
    qapp.processEvents()
    return (ws1, ws2), (a1, a2), (t1, t2, t3)


def test_mirror_popula_por_sinais(main_window, qapp):
    _setup_consoles(main_window, qapp)
    assert main_window.global_tab_bar._bar.count() == 3


def test_ativar_pela_tab_troca_area_e_console(main_window, qapp):
    from claude_workspaces.ui.terminal_widget import tab_uid_of

    _ws, (a1, _a2), (_t1, t2, _t3) = _setup_consoles(main_window, qapp)
    uid2 = tab_uid_of(t2)
    main_window._on_global_tab_activate(uid2)
    qapp.processEvents()
    assert a1.current_uid() == uid2
    assert main_window.terminal_host.currentWidget() is a1


def test_fechar_pela_tab_remove_do_mirror(main_window, qapp):
    from claude_workspaces.ui.terminal_widget import tab_uid_of

    _ws, _areas, (_t1, _t2, t3) = _setup_consoles(main_window, qapp)
    main_window._on_global_tab_close(tab_uid_of(t3))
    qapp.processEvents()
    qapp.processEvents()
    assert main_window.global_tab_bar._bar.count() == 2


def test_tooltip_mostra_console_e_workspace(main_window, qapp):
    _setup_consoles(main_window, qapp)
    bar = main_window.global_tab_bar._bar
    assert "alpha" in bar.tabToolTip(0)


def test_uid_helpers_da_area(main_window, qapp):
    from claude_workspaces.ui.terminal_widget import tab_uid_of

    _ws, (a1, _a2), (t1, t2, _t3) = _setup_consoles(main_window, qapp)
    assert a1.uid_at(0) == tab_uid_of(t1)
    assert a1.index_of_uid(tab_uid_of(t2)) == 1
    assert a1.index_of_uid(999999) == -1
    assert a1.close_tab_by_uid(tab_uid_of(t1)) is True
    assert a1.index_of_uid(tab_uid_of(t1)) == -1
