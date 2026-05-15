from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .terminal_widget import TerminalWidget


class TerminalArea(QWidget):
    """Wrapper de QTabWidget com abas de terminal — uma instância por workspace.
    Mantém o estado das sessões mesmo quando o usuário alterna entre workspaces."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)
        return widget

    def count(self) -> int:
        return self.tabs.count()

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if isinstance(widget, TerminalWidget):
            widget.terminate()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def close_all(self) -> None:
        while self.tabs.count():
            self._close_tab(0)
