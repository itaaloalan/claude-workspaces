from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStackedLayout, QTabBar, QVBoxLayout, QWidget

from . import theme
from .terminal_child_widget import (
    STATE_AWAITING,
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_WORKING,
)
from .terminal_widget import TerminalWidget

# Cor do texto da aba em função do status do console. Mantém paridade
# com o STATE_COLOR usado nas linhas da sidebar — usuário vê de relance
# qual aba está rodando / ociosa / aguardando.
_TAB_COLOR = {
    STATE_WORKING: QColor(theme.WARNING),
    STATE_AWAITING: QColor(theme.WAITING),
    STATE_IDLE: QColor(theme.DANGER),
    STATE_DONE: QColor(theme.SUCCESS),
    STATE_ERROR: QColor(theme.DANGER),
}
_TAB_COLOR_DEFAULT = QColor(theme.TEXT_MUTED)

_TABBAR_QSS = (
    "QTabBar { background: #0e0e0e; }"
    "QTabBar::tab { background: #0e0e0e; "
    "  padding: 4px 12px; border: 0; "
    "  border-right: 1px solid #2a2a2a; "
    "  font-size: 11px; min-height: 18px; }"
    "QTabBar::tab:selected { background: #0e0e0e; "
    "  border-bottom: 2px solid #3d6ea8; }"
)


class _TabsCompat(QObject):
    """Shim que preserva a API `area.tabs.*` usada por main_window.py e
    terminal_coordinator.py após o TerminalArea trocar o QTabWidget interno
    por QTabBar + QStackedLayout (StackAll). Expõe só o subconjunto externo:
    count/widget/currentWidget/currentIndex/setCurrentIndex/tabText +
    o sinal currentChanged."""

    currentChanged = Signal(int)  # re-emitido pelo TerminalArea ao trocar

    def __init__(self, area: "TerminalArea") -> None:
        super().__init__(area)
        self._area = area

    def addTab(self, widget: QWidget, label: str) -> int:
        """Compat com QTabWidget.addTab — adiciona ao stack + barra mantendo
        os índices alinhados. Retorna o índice."""
        idx = self._area._stack.addWidget(widget)
        self._area._bar.insertTab(idx, label)
        self._area._refresh_tab_bar_visibility()
        return idx

    def count(self) -> int:
        return self._area._bar.count()

    def widget(self, i: int) -> QWidget | None:
        return self._area._stack.widget(i)

    def currentWidget(self) -> QWidget | None:
        return self._area._stack.currentWidget()

    def currentIndex(self) -> int:
        return self._area._bar.currentIndex()

    def setCurrentIndex(self, i: int) -> None:
        self._area._set_current_index(i)

    def tabText(self, i: int) -> str:
        return self._area._bar.tabText(i)


class TerminalArea(QWidget):
    """Abas de terminal — uma instância por workspace. Mantém o estado das
    sessões mesmo quando o usuário alterna entre workspaces.

    Internamente usa QTabBar (barra) + QStackedLayout em modo StackAll (todas
    as webviews ficam compostas/vivas, a ativa no topo) em vez de QTabWidget.
    Motivo: o QTabWidget esconde a página inativa, e o QtWebEngine libera a
    superfície de GPU das views escondidas — mostrar de novo travava a UI
    thread ("congela e depois troca"). Com StackAll nada é escondido, então
    trocar de console é só um raise da view ativa (instantâneo)."""

    running_count_changed = Signal(int)
    # tab_id, exit_code — re-emitido pelo TerminalCoordinator e finalmente
    # consumido pelo MainWindow pra emitir task_completed/task_failed.
    tab_session_exited = Signal("qint64", int)
    # tab_id é id() do widget — pode passar de 2^31, então usa qint64
    # (tab_id, title, status, is_working, is_running, needs_decision)
    tab_activity_changed = Signal("qint64", str, str, bool, bool, bool)
    tab_removed = Signal("qint64")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running_count = 0

        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Barra de abas: visível quando há ≥2 consoles — permite trocar de
        # console sem depender de sub-itens na sidebar.
        self._bar = QTabBar()
        self._bar.setMinimumWidth(0)
        self._bar.setTabsClosable(True)
        self._bar.setMovable(True)
        self._bar.setDocumentMode(True)
        self._bar.setExpanding(False)
        self._bar.setDrawBase(False)
        self._bar.setStyleSheet(_TABBAR_QSS)
        self._bar.setVisible(False)
        self._bar.tabCloseRequested.connect(self._close_tab)
        self._bar.currentChanged.connect(self._on_bar_current_changed)
        self._bar.tabMoved.connect(self._on_tab_moved)
        layout.addWidget(self._bar)

        # Conteúdo: StackAll mantém todas as webviews vivas; a "atual" fica
        # no topo. bg do terminal pra evitar faixa branca atrás das views.
        self._content = QWidget()
        self._content.setStyleSheet("background: #0e0e0e;")
        self._content.setMinimumWidth(0)
        self._stack = QStackedLayout(self._content)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        layout.addWidget(self._content, stretch=1)

        # Shim de compatibilidade pra `area.tabs.*`.
        self.tabs = _TabsCompat(self)

    # ---------- sincronização bar <-> stack ----------

    def _set_current_index(self, i: int) -> None:
        """Fonte única de verdade do "console ativo": move a barra; o
        handler de currentChanged sincroniza o stack/foco e re-emite."""
        if 0 <= i < self._bar.count():
            self._bar.setCurrentIndex(i)

    def _on_bar_current_changed(self, idx: int) -> None:
        if 0 <= idx < self._stack.count():
            self._stack.setCurrentIndex(idx)  # StackAll: marca o atual
            self.focus_active_console()
        self._refresh_tab_bar_visibility()
        self.tabs.currentChanged.emit(idx)

    def focus_active_console(self) -> None:
        """Traz o console ativo pro topo do z-order (StackAll) e manda o foco
        pra webview, pra digitação cair no console certo sem clique do mouse."""
        w = self._stack.currentWidget()
        if w is not None:
            # StackAll deixa todas visíveis; garante a ativa no topo do
            # z-order e manda o foco pra webview (input no console certo).
            w.raise_()
            view = getattr(w, "view", None)
            (view or w).setFocus()

    def _on_tab_moved(self, from_idx: int, to_idx: int) -> None:
        """Mantém o stack na mesma ordem da barra quando o usuário arrasta
        uma aba."""
        w = self._stack.widget(from_idx)
        if w is None:
            return
        self._stack.removeWidget(w)
        self._stack.insertWidget(to_idx, w)
        # Re-sincroniza o topo com a aba atual (índices mudaram).
        self._stack.setCurrentIndex(self._bar.currentIndex())
        self._refresh_all_tab_texts()

    # ---------- API pública ----------

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
        widget.session_exited.connect(
            lambda code, w=widget: self.tab_session_exited.emit(id(w), code)
        )
        idx = self._stack.addWidget(widget)
        self._bar.insertTab(idx, title)
        self._set_current_index(idx)
        widget.setProperty("_base_title", title)
        # Texto inicial já com `#N` (mesmo formato do sidebar).
        self._bar.setTabText(idx, f"✓ {self._compute_tab_display(widget)}")
        self._apply_tab_color(idx, widget)
        self._refresh_tab_bar_visibility()
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
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
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
        idx = self._stack.indexOf(widget)
        if idx < 0:
            return
        display = self._compute_tab_display(widget)
        prefix = "●" if running else "✓"
        self._bar.setTabText(idx, f"{prefix} {display}")
        self._apply_tab_color(idx, widget)

    def _apply_tab_color(self, idx: int, widget: TerminalWidget) -> None:
        """Pinta o texto da aba na cor do status atual (idle vermelho,
        working amber, awaiting laranja, done verde). Quando o processo
        nem subiu ainda, fica no muted padrão."""
        if not widget.is_running():
            self._bar.setTabTextColor(idx, _TAB_COLOR_DEFAULT)
            return
        color = _TAB_COLOR.get(widget._last_status, _TAB_COLOR_DEFAULT)
        self._bar.setTabTextColor(idx, color)

    def _emit_activity(
        self,
        widget: TerminalWidget,
        status: str,
        is_working: bool,
        needs_decision: bool = False,
    ) -> None:
        idx = self._stack.indexOf(widget)
        if idx < 0:
            return
        # Preferir o título da sessão Claude (primeiro user prompt) se
        # já tiver sido resolvido; fallback pro título base da aba
        title = widget.effective_title()
        # Espelha o texto da aba: rename via sidebar (set_custom_name)
        # dispara activity_changed → o tab passa a refletir o nome custom
        # com prefixo `#N` igual ao sidebar.
        prefix = "●" if widget.is_running() else "✓"
        self._bar.setTabText(idx, f"{prefix} {self._compute_tab_display(widget)}")
        self._apply_tab_color(idx, widget)
        self.tab_activity_changed.emit(
            id(widget),
            title,
            status,
            is_working,
            widget.is_running(),
            needs_decision,
        )

    def count(self) -> int:
        return self._bar.count()

    def running_count(self) -> int:
        return self._running_count

    def _on_running_changed(self, running: bool) -> None:
        self._running_count += 1 if running else -1
        if self._running_count < 0:
            self._running_count = 0
        self.running_count_changed.emit(self._running_count)

    def _close_tab(self, index: int) -> None:
        widget = self._stack.widget(index)
        tab_id = id(widget) if widget is not None else 0
        if isinstance(widget, TerminalWidget):
            widget.terminate()
            widget.release_session_claim()
        self._bar.removeTab(index)
        if widget is not None:
            self._stack.removeWidget(widget)
            widget.deleteLater()
            self.tab_removed.emit(tab_id)
        # Renumera os tabs restantes: ao fechar #1, #2 vira #1, etc.
        # Sem isso, posições ficariam "furadas" até a próxima atividade.
        self._refresh_all_tab_texts()
        self._refresh_tab_bar_visibility()

    def _refresh_tab_bar_visibility(self) -> None:
        """Mostra a tab bar quando há ≥2 consoles; esconde quando há apenas 1.
        Com a sidebar flat (sem sub-itens), a tab bar é o único meio de
        alternar entre consoles de um workspace."""
        self._bar.setVisible(self._bar.count() > 1)

    def _refresh_all_tab_texts(self) -> None:
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if isinstance(w, TerminalWidget):
                prefix = "●" if w.is_running() else "✓"
                self._bar.setTabText(i, f"{prefix} {self._compute_tab_display(w)}")
                self._apply_tab_color(i, w)

    def close_all(self) -> None:
        while self._bar.count():
            self._close_tab(0)
