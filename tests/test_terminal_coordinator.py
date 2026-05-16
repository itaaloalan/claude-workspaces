"""Testes de fluxo crítico do TerminalCoordinator.

Não testa o widget TerminalArea em si (precisaria de QWebEngineView).
Foca em: transição working→idle vira inbox; release_tab cascateia;
spinner liga/desliga; multi-tab tracking.
"""

from unittest.mock import MagicMock

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
def coord(qapp):
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
