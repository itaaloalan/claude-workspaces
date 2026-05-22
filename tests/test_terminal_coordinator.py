"""Testes de fluxo crítico do TerminalCoordinator.

Não testa o widget TerminalArea em si (precisaria de QWebEngineView).
Foca em: transição working→idle vira inbox; release_tab cascateia;
spinner liga/desliga; multi-tab tracking.
"""


import pytest
from PySide6.QtWidgets import QApplication

from claude_workspaces.ui.coordinators.terminal_coordinator import (
    TerminalCoordinator,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def coord(qapp, monkeypatch):
    # Zera o threshold de duração mínima de working pra que transições
    # working→idle síncronas nos testes contem normalmente como inbox.
    monkeypatch.setattr(TerminalCoordinator, "_MIN_WORKING_DURATION_S", 0.0)
    return TerminalCoordinator()


def test_activity_no_transition_no_inbox(coord):
    """Estado inicial → não-working: sem inbox."""
    inbox_emits = []
    coord.inbox_changed.connect(lambda c: inbox_emits.append(c))
    coord._on_tab_activity("ws1", 1001, "claude #1", "idle", False, True)
    assert coord.inbox_count() == 0
    assert inbox_emits == []


def test_working_to_idle_triggers_inbox(coord):
    """Transição working→idle adiciona ao inbox."""
    inbox_emits = []
    coord.inbox_changed.connect(lambda c: inbox_emits.append(c))
    coord._on_tab_activity("ws1", 1001, "claude #1", "thinking", True, True)
    coord._on_tab_activity("ws1", 1001, "claude #1", "auto mode on", False, True)
    assert coord.inbox_count() == 1
    assert inbox_emits[-1] == 1


def test_working_flicker_below_threshold_no_inbox(qapp, monkeypatch):
    """Flicker working→idle abaixo do threshold mínimo NÃO vira inbox.

    Reproduz o cenário "abre novo terminal → ✅ Pronto fantasma": parser
    cai no fallback `recent` durante render do welcome banner, vira
    working brevemente, depois flipa pra idle quando output dá pausa.
    """
    monkeypatch.setattr(TerminalCoordinator, "_MIN_WORKING_DURATION_S", 1.5)
    coord = TerminalCoordinator()
    alerts = []
    coord.inbox_alert.connect(lambda *a: alerts.append(a))
    coord._on_tab_activity("ws1", 1001, "claude #1", "thinking", True, True)
    # Transição síncrona = duração ~0s, muito abaixo de 1.5s
    coord._on_tab_activity("ws1", 1001, "claude #1", "auto mode on", False, True)
    assert coord.inbox_count() == 0
    assert alerts == []


def test_idle_to_working_clears_inbox(coord):
    """Voltar a trabalhar saindo da fila de espera."""
    coord._on_tab_activity("ws1", 1001, "claude #1", "thinking", True, True)
    coord._on_tab_activity("ws1", 1001, "claude #1", "waiting", False, True)
    assert coord.inbox_count() == 1
    coord._on_tab_activity("ws1", 1001, "claude #1", "thinking again", True, True)
    assert coord.inbox_count() == 0


def test_terminated_clears_inbox(coord):
    """is_running=False também limpa do inbox."""
    coord._on_tab_activity("ws1", 1001, "claude #1", "thinking", True, True)
    coord._on_tab_activity("ws1", 1001, "claude #1", "idle", False, True)
    assert coord.inbox_count() == 1
    coord._on_tab_activity("ws1", 1001, "claude #1", "done", False, False)
    assert coord.inbox_count() == 0


def test_release_tab_removes_from_inbox(coord):
    """remove_tab limpa o tab inteiro do estado."""
    coord._on_tab_activity("ws1", 2001, "claude #1", "x", True, True)
    coord._on_tab_activity("ws1", 2001, "claude #1", "idle", False, True)
    assert coord.inbox_count() == 1
    coord._on_tab_removed(2001)
    assert coord.inbox_count() == 0
    assert 2001 not in coord.state.activity


def test_spinner_starts_with_working(coord):
    """Spinner timer só liga quando há alguém working."""
    assert not coord._spinner_timer.isActive()
    coord._on_tab_activity("ws1", 1, "x", "thinking", True, True)
    assert coord._spinner_timer.isActive()
    coord._on_tab_activity("ws1", 1, "x", "idle", False, True)
    assert not coord._spinner_timer.isActive()


def test_spinner_keeps_with_other_working(coord):
    """Múltiplos tabs: spinner não para enquanto algum tá working."""
    coord._on_tab_activity("ws1", 1, "a", "x", True, True)
    coord._on_tab_activity("ws1", 2, "b", "x", True, True)
    assert coord._spinner_timer.isActive()
    coord._on_tab_activity("ws1", 1, "a", "idle", False, True)
    assert coord._spinner_timer.isActive()  # 2 ainda working
    coord._on_tab_activity("ws1", 2, "b", "idle", False, True)
    assert not coord._spinner_timer.isActive()


def test_running_count(coord):
    """set_running_count via signal."""
    emits = []
    coord.workspace_running_changed.connect(lambda ws, c: emits.append((ws, c)))
    coord._on_running_count_changed("ws1", 3)
    coord._on_running_count_changed("ws1", 0)
    assert emits == [("ws1", 3), ("ws1", 0)]
    assert coord.state.running_count_of("ws1") == 0


def test_inbox_entries_includes_metadata(coord):
    coord._on_tab_activity("ws1", 7, "claude #1", "Cooking…", True, True)
    coord._on_tab_activity("ws1", 7, "claude #1", "Aguardando confirmação", False, True)
    entries = coord.inbox_entries()
    assert 7 in entries
    assert entries[7]["workspace_id"] == "ws1"
    assert entries[7]["title"] == "claude #1"
    assert "confirmação" in entries[7]["status"]


def test_clear_inbox(coord):
    coord._on_tab_activity("ws1", 1, "a", "x", True, True)
    coord._on_tab_activity("ws1", 1, "a", "idle", False, True)
    assert coord.inbox_count() == 1
    coord.clear_inbox()
    assert coord.inbox_count() == 0


def test_remove_from_inbox(coord):
    coord._on_tab_activity("ws1", 1, "a", "x", True, True)
    coord._on_tab_activity("ws1", 1, "a", "idle", False, True)
    coord.remove_from_inbox(1)
    assert coord.inbox_count() == 0


def test_current_spinner_char_rotates(coord):
    a = coord.current_spinner_char()
    coord._tick_spinner()
    b = coord.current_spinner_char()
    assert a != b


# ---------- inbox_entry_removed ----------


def test_inbox_entry_removed_on_back_to_working(coord):
    """Quando o tab volta pra working, emite inbox_entry_removed pra UI
    poder fechar a notificação D-Bus correspondente."""
    removed = []
    coord.inbox_entry_removed.connect(lambda tid: removed.append(tid))
    coord._on_tab_activity("ws1", 1, "x", "thinking", True, True)
    coord._on_tab_activity("ws1", 1, "x", "idle", False, True)
    coord._on_tab_activity("ws1", 1, "x", "thinking again", True, True)
    assert removed == [1]


def test_inbox_entry_removed_on_terminate(coord):
    """is_running=False também deve fechar a notificação."""
    removed = []
    coord.inbox_entry_removed.connect(lambda tid: removed.append(tid))
    coord._on_tab_activity("ws1", 2, "x", "thinking", True, True)
    coord._on_tab_activity("ws1", 2, "x", "idle", False, True)
    coord._on_tab_activity("ws1", 2, "x", "done", False, False)
    assert removed == [2]


def test_inbox_entry_removed_on_explicit_remove(coord):
    """remove_from_inbox/clear_inbox/dismiss via API também emitem."""
    removed = []
    coord.inbox_entry_removed.connect(lambda tid: removed.append(tid))
    coord._on_tab_activity("ws1", 3, "x", "thinking", True, True)
    coord._on_tab_activity("ws1", 3, "x", "idle", False, True)
    coord.remove_from_inbox(3)
    assert removed == [3]


def test_inbox_entry_removed_on_tab_focused(coord):
    """Clicar na aba (foco) tira do inbox e fecha a notificação."""
    from PySide6.QtWidgets import QWidget

    from claude_workspaces.ui.terminal_area import TerminalArea

    area = TerminalArea()
    placeholder = QWidget()
    area.tabs.addTab(placeholder, "stub")
    tab_id = id(placeholder)
    coord._on_tab_activity("ws1", tab_id, "x", "thinking", True, True)
    coord._on_tab_activity("ws1", tab_id, "x", "idle", False, True)
    assert coord.inbox_count() == 1

    removed = []
    coord.inbox_entry_removed.connect(lambda tid: removed.append(tid))
    coord._on_tab_focused(area, 0)
    assert removed == [tab_id]


def test_inbox_entry_removed_on_clear_inbox(coord):
    """clear_inbox emite um sinal por entrada removida."""
    coord._on_tab_activity("ws1", 4, "a", "x", True, True)
    coord._on_tab_activity("ws1", 4, "a", "idle", False, True)
    coord._on_tab_activity("ws1", 5, "b", "x", True, True)
    coord._on_tab_activity("ws1", 5, "b", "idle", False, True)
    removed = []
    coord.inbox_entry_removed.connect(lambda tid: removed.append(tid))
    coord.clear_inbox()
    assert sorted(removed) == [4, 5]
