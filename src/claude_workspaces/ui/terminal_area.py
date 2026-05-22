from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .terminal_widget import TerminalWidget


class TerminalArea(QWidget):
    """Wrapper de QTabWidget com abas de terminal — uma instância por workspace.
    Mantém o estado das sessões mesmo quando o usuário alterna entre workspaces."""

    running_count_changed = Signal(int)
    # tab_id é id() do widget — pode passar de 2^31, então usa qint64
    # (tab_id, title, status, is_working, is_running, needs_decision)
    tab_activity_changed = Signal("qint64", str, str, bool, bool, bool)
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
        # QSS pra match com a tab bar externa do _terminal_tabs — sem
        # bordas estranhas. Tab ativa com underline azul fino. Pane com
        # bg do terminal pra evitar faixa branca atrás dos terminais
        # antes de renderizar.
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; background: #0e0e0e; }"
            "QTabBar { background: #0e0e0e; }"
            "QTabBar::tab { background: #0e0e0e; color: #9aa0a6; "
            "  padding: 4px 12px; border: 0; "
            "  border-right: 1px solid #2a2a2a; "
            "  font-size: 11px; min-height: 18px; }"
            "QTabBar::tab:selected { background: #0e0e0e; color: #e6e6e6; "
            "  border-bottom: 2px solid #3d6ea8; }"
            "QTabBar::tab:hover:!selected { color: #c8c8c8; }"
        )
        self.tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self.tabs)

    def add_terminal(self, title: str) -> TerminalWidget:
        widget = TerminalWidget()
        widget.running_changed.connect(self._on_running_changed)
        widget.running_changed.connect(
            lambda running, w=widget: self._mark_tab_state(w, running)
        )
        widget.running_changed.connect(
            lambda running, w=widget: self._emit_activity(
                w, w._last_status, running, w._last_needs_decision
            )
        )
        widget.activity_changed.connect(
            lambda status, working, needs_decision, w=widget: self._emit_activity(
                w, status, working, needs_decision
            )
        )
        idx = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(idx)
        widget.setProperty("_base_title", title)
        # Texto inicial já com `#N` (mesmo formato do sidebar).
        self.tabs.setTabText(idx, f"✓ {self._compute_tab_display(widget)}")
        # Emite estado inicial
        self.tab_activity_changed.emit(id(widget), title, "", False, False, False)
        return widget

    def _compute_tab_display(self, widget: TerminalWidget) -> str:
        """Mesmo formato `#N Title` usado no sidebar: N é a posição entre
        os irmãos ordenados por `id(widget)` crescente (mais antigo = #1).
        Title é o `effective_title()` do widget — espelha custom_name /
        session_preview / base_title, então renomear via sidebar reflete
        aqui imediatamente."""
        sibling_ids: list[int] = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w is not None:
                sibling_ids.append(id(w))
        sibling_ids.sort()
        wid = id(widget)
        if wid in sibling_ids:
            position = sibling_ids.index(wid) + 1
        else:
            position = len(sibling_ids) + 1
        title = widget.effective_title() or (widget.property("_base_title") or "")
        return f"#{position} {title}".rstrip()

    def _mark_tab_state(self, widget: TerminalWidget, running: bool) -> None:
        idx = self.tabs.indexOf(widget)
        if idx < 0:
            return
        display = self._compute_tab_display(widget)
        prefix = "●" if running else "✓"
        self.tabs.setTabText(idx, f"{prefix} {display}")

    def _emit_activity(
        self,
        widget: TerminalWidget,
        status: str,
        is_working: bool,
        needs_decision: bool = False,
    ) -> None:
        idx = self.tabs.indexOf(widget)
        if idx < 0:
            return
        # Preferir o título da sessão Claude (primeiro user prompt) se
        # já tiver sido resolvido; fallback pro título base da aba
        title = widget.effective_title()
        # Espelha o texto da aba: rename via sidebar (set_custom_name)
        # dispara activity_changed → o tab passa a refletir o nome custom
        # com prefixo `#N` igual ao sidebar.
        prefix = "●" if widget.is_running() else "✓"
        self.tabs.setTabText(idx, f"{prefix} {self._compute_tab_display(widget)}")
        self.tab_activity_changed.emit(
            id(widget),
            title,
            status,
            is_working,
            widget.is_running(),
            needs_decision,
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
            widget.release_session_claim()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
            self.tab_removed.emit(tab_id)
        # Renumera os tabs restantes: ao fechar #1, #2 vira #1, etc.
        # Sem isso, posições ficariam "furadas" até a próxima atividade.
        self._refresh_all_tab_texts()

    def _refresh_all_tab_texts(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TerminalWidget):
                prefix = "●" if w.is_running() else "✓"
                self.tabs.setTabText(i, f"{prefix} {self._compute_tab_display(w)}")

    def close_all(self) -> None:
        while self.tabs.count():
            self._close_tab(0)
