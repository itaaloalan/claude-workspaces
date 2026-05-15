from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .terminal_widget import TerminalWidget


class TerminalArea(QWidget):
    """Wrapper de QTabWidget com abas de terminal — uma instância por workspace.
    Mantém o estado das sessões mesmo quando o usuário alterna entre workspaces."""

    running_count_changed = Signal(int)
    # tab_id é id() do widget — pode passar de 2^31, então usa qint64
    tab_activity_changed = Signal("qint64", str, str, bool, bool)
    tab_removed = Signal("qint64")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self.tabs)

    def add_terminal(self, title: str) -> TerminalWidget:
        widget = TerminalWidget()
        widget.running_changed.connect(self._on_running_changed)
        widget.running_changed.connect(
            lambda running, w=widget: self._mark_tab_state(w, running)
        )
        widget.running_changed.connect(
            lambda running, w=widget: self._emit_activity(w, w._last_status, running)
        )
        widget.activity_changed.connect(
            lambda status, working, w=widget: self._emit_activity(w, status, working)
        )
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)
        widget.setProperty("_base_title", title)
        # Emite estado inicial
        self.tab_activity_changed.emit(id(widget), title, "", False, False)
        return widget

    def _mark_tab_state(self, widget: TerminalWidget, running: bool) -> None:
        idx = self.tabs.indexOf(widget)
        if idx < 0:
            return
        base = widget.property("_base_title") or self.tabs.tabText(idx).lstrip("✓● ")
        if running:
            self.tabs.setTabText(idx, f"● {base}")
        else:
            self.tabs.setTabText(idx, f"✓ {base}")

    def _emit_activity(
        self, widget: TerminalWidget, status: str, is_working: bool
    ) -> None:
        if self.tabs.indexOf(widget) < 0:
            return
        title = widget.property("_base_title") or ""
        self.tab_activity_changed.emit(
            id(widget), title, status, is_working, widget.is_running()
        )

    def count(self) -> int:
        return self.tabs.count()

    def running_count(self) -> int:
        return self._running_count

    def _on_running_changed(self, running: bool) -> None:
        self._running_count += 1 if running else -1
        if self._running_count < 0:
            self._running_count = 0
        self.running_count_changed.emit(self._running_count)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        tab_id = id(widget) if widget is not None else 0
        if isinstance(widget, TerminalWidget):
            widget.terminate()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
            self.tab_removed.emit(tab_id)

    def close_all(self) -> None:
        while self.tabs.count():
            self._close_tab(0)
