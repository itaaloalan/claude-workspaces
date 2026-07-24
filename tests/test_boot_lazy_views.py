"""Boot sem thundering herd: restore não pode materializar N WebEngines.

O restore de 9 sessões materializava 9 QWebEngineViews (cada aba nova virava
current; sob StackAll toda área "parece" visível; RunnerWidget criava view no
construtor) — main thread travada ~24s no boot. Estes testes fixam:
`add_terminal(make_current=False)` não promove a aba, o probe de área ativa
bloqueia materialização de área não-exposta, e o RunnerWidget nasce sem view.
"""
from __future__ import annotations

from claude_workspaces.models import RunnerConfig
from claude_workspaces.ui import terminal_area as ta
from claude_workspaces.ui.runner_widget import RunnerWidget
from claude_workspaces.ui.terminal_area import TerminalArea, set_active_area_probe


def _make_area(qapp) -> TerminalArea:
    return TerminalArea()


def test_add_terminal_make_current_false_keeps_current(qapp):
    area = _make_area(qapp)
    try:
        w1 = area.add_terminal("um")
        assert area._stack.currentWidget() is w1
        w2 = area.add_terminal("dois", make_current=False)
        # A aba nova entrou mas o current não mudou.
        assert area._stack.count() == 2
        assert area._stack.currentWidget() is w1
        w3 = area.add_terminal("tres")  # default: promove
        assert area._stack.currentWidget() is w3
        assert w2 is not None
    finally:
        area.deleteLater()


def test_first_tab_becomes_current_even_without_promote(qapp):
    """A PRIMEIRA aba de uma área vazia vira current (auto do QTabBar) —
    comportamento desejado: o workspace ativo materializa 1 view no boot."""
    area = _make_area(qapp)
    try:
        w1 = area.add_terminal("um", make_current=False)
        assert area._stack.currentWidget() is w1
    finally:
        area.deleteLater()


def test_inactive_area_does_not_enqueue_materialization(qapp, monkeypatch):
    area = _make_area(qapp)
    try:
        enqueued: list = []
        monkeypatch.setattr(
            ta._get_materialize_queue(), "enqueue",
            lambda a, w: enqueued.append(w),
        )
        set_active_area_probe(lambda a: False)  # nenhuma área é a ativa
        area.add_terminal("um")
        area._materialize_current_view()
        assert enqueued == []
        set_active_area_probe(lambda a: True)
        area._materialize_current_view()
        assert len(enqueued) == 1
    finally:
        set_active_area_probe(None)
        area.deleteLater()


def test_probe_none_is_permissive(qapp, monkeypatch):
    """Sem probe registrado (testes/legado) o comportamento é o antigo."""
    area = _make_area(qapp)
    try:
        set_active_area_probe(None)
        enqueued: list = []
        monkeypatch.setattr(
            ta._get_materialize_queue(), "enqueue",
            lambda a, w: enqueued.append(w),
        )
        area.add_terminal("um")
        area._materialize_current_view()
        assert len(enqueued) == 1
    finally:
        area.deleteLater()


def test_area_deactivated_schedules_unload_activated_cancels(qapp):
    from PySide6.QtWidgets import QWidget

    area = _make_area(qapp)
    try:
        w1 = area.add_terminal("um")
        # Simula view materializada (schedule_unload é no-op sem view).
        w1._view_built = True
        w1.view = QWidget()
        area.on_area_deactivated()
        assert w1._unload_timer.isActive()
        area.on_area_activated()
        assert not w1._unload_timer.isActive()
    finally:
        w1.view = None
        w1._view_built = False
        area.deleteLater()


def test_runner_widget_has_no_eager_view(qapp):
    """RunnerWidget nasce SEM QWebEngineView — o showEvent constrói quando o
    pane aparece. PTY/log capture funcionam sem a view."""
    w = RunnerWidget(
        RunnerConfig(name="api", start_cmd="echo hi"), default_cwd="/tmp"
    )
    try:
        assert w.view is None
        # Log capture segue vivo sem a view (gate _live fechado, _log_buf).
        w.session.output_received.emit(b"log sem view\n")
        assert "log sem view" in w._log_buf
        # _build_view sob demanda funciona (showEvent chama isto).
        w._build_view()
        assert w.view is not None
    finally:
        w.terminate()
        w.deleteLater()
