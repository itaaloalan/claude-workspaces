from PySide6.QtCore import QObject, QTimer, Signal
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
from .terminal_widget import TerminalWidget, note_view_destroyed_externally, tab_uid_of


class _MaterializeQueue(QObject):
    """Serializa ensure_view_loaded() (criação de QWebEngineView) entre
    TODAS as TerminalArea da janela, uma de cada vez.

    Várias áreas materializando webviews no mesmo tick do event loop — como
    no boot, quando N sessões restauradas viram "atual" em sequência e cada
    TerminalArea dispara seu timer coalescente(0ms) — produz uma rajada de
    QWebEngineView sendo construídas quase simultaneamente. Isso reproduziu
    um SIGSEGV nativo (reentrada em PySide::getWrapperForQObject via
    QObject::doSetProperty, tanto por foco quanto por QWebEngineUrlRequestJob)
    em coredumps do processo. Espaçar as criações elimina a concorrência que
    dispara o bug."""

    _STAGGER_MS = 120

    def __init__(self) -> None:
        super().__init__()
        self._pending: list[tuple["TerminalArea", TerminalWidget]] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dispatch_next)

    def enqueue(self, area: "TerminalArea", w: TerminalWidget) -> None:
        self._pending.append((area, w))
        if not self._timer.isActive():
            self._timer.start(0)

    def _dispatch_next(self) -> None:
        if not self._pending:
            return
        # Recycle do renderer em andamento: segura a fila inteira (sem
        # perder o pending) — uma page criada agora nasceria no renderer
        # moribundo e impediria o processo de morrer.
        from ..services.webengine_recycler import recycling_active
        if recycling_active():
            self._timer.start(250)
            return
        area, w = self._pending.pop(0)
        try:
            # Só materializa a aba current da ÁREA ATIVA do host — área de
            # workspace não-exposto (StackAll faz todas parecerem visíveis)
            # re-materializa quando for ativada (on_area_activated).
            if area._stack.currentWidget() is w and _area_is_active(area):
                w.ensure_view_loaded()
                area.focus_active_console()
        except RuntimeError:
            pass  # área ou console fechado antes de materializar
        if self._pending:
            self._timer.start(self._STAGGER_MS)


_materialize_queue: "_MaterializeQueue | None" = None


def _get_materialize_queue() -> "_MaterializeQueue":
    global _materialize_queue
    if _materialize_queue is None:
        _materialize_queue = _MaterializeQueue()
    return _materialize_queue


# Probe "esta área é a ativa do terminal_host?" — injetado pela MainWindow.
# Necessário porque o host usa QStackedLayout.StackAll: TODAS as áreas ficam
# "visíveis" (compostas), então isVisible()/showEvent não distinguem o
# workspace realmente exposto e, sem o probe, o restore de boot materializava
# uma QWebEngineView por sessão restaurada (9 views num boot travado de 24s).
# None (testes / antes do wiring) = permissivo, comporta como antes.
_active_area_probe = None


def set_active_area_probe(fn) -> None:
    global _active_area_probe
    _active_area_probe = fn


def _area_is_active(area: "TerminalArea") -> bool:
    if _active_area_probe is None:
        return True
    try:
        return bool(_active_area_probe(area))
    except RuntimeError:
        return False  # host/área destruídos durante teardown

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
    "QTabBar { background: #121110; }"
    "QTabBar::tab { background: #121110; "
    "  padding: 4px 12px; border: 0; "
    "  border-right: 1px solid #2d2b26; "
    "  font-size: 11px; min-height: 18px; }"
    "QTabBar::tab:selected { background: #121110; "
    "  border-bottom: 2px solid #d4a04a; }"
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
        self._content.setStyleSheet("background: #121110;")
        self._content.setMinimumWidth(0)
        self._stack = QStackedLayout(self._content)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        layout.addWidget(self._content, stretch=1)

        # Shim de compatibilidade pra `area.tabs.*`.
        self.tabs = _TabsCompat(self)

        # Lazy-load dos consoles: o WebView de cada console só é criado
        # quando a aba fica ativa. Timer coalescente (0ms) — no startup
        # várias sessões são restauradas em sequência, cada uma virando
        # "atual" por um instante; o timer dispara uma vez só no fim e
        # materializa apenas a aba que ficou realmente ativa.
        self._materialize_timer = QTimer(self)
        self._materialize_timer.setSingleShot(True)
        self._materialize_timer.setInterval(0)
        self._materialize_timer.timeout.connect(self._materialize_current_view)

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
            # Lazy-load: agenda a criação do WebView do console que ficou
            # ativo (coalescido p/ não materializar tudo durante o restore).
            self._materialize_timer.start()
            # Lazy-unload: o StackAll mantém todas as views vivas, então a
            # troca de aba não dispara hideEvent. Arma o descarregamento dos
            # consoles que saíram de foco e cancela o do que ficou ativo.
            for i in range(self._stack.count()):
                w = self._stack.widget(i)
                if isinstance(w, TerminalWidget):
                    if i == idx:
                        w.cancel_unload()
                    else:
                        w.schedule_unload()
        self._refresh_tab_bar_visibility()
        self.tabs.currentChanged.emit(idx)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # Área inteira oculta (troca de workspace): agenda lazy-unload de todos
        # os consoles desta área.
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if isinstance(w, TerminalWidget):
                w.schedule_unload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Área voltou a ficar visível: cancela o unload do console ativo e o
        # (re)materializa caso tenha sido descarregado enquanto oculto.
        # Gate de área ativa: sob StackAll, TODA área recebe showEvent quando
        # o pane aparece — sem o probe isso materializava as views de todos
        # os workspaces no boot.
        if not _area_is_active(self):
            return
        cur = self._stack.currentWidget()
        if isinstance(cur, TerminalWidget):
            cur.cancel_unload()
        self._materialize_timer.start()

    def on_area_activated(self) -> None:
        """Chamado pela MainWindow quando esta área vira a current do
        terminal_host (troca de workspace). Sob StackAll não há
        show/hideEvent nessa troca — este é o par explícito."""
        cur = self._stack.currentWidget()
        if isinstance(cur, TerminalWidget):
            cur.cancel_unload()
        self._materialize_timer.start()

    def on_area_deactivated(self) -> None:
        """Par do on_area_activated: área deixou de ser a current do host.
        Agenda o lazy-unload de todos os consoles (90s) — antes disso a view
        current de cada workspace vivia pra sempre (StackAll nunca esconde)."""
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if isinstance(w, TerminalWidget):
                w.schedule_unload()

    def _materialize_current_view(self) -> None:
        """Enfileira a criação do WebView do console ativo sob demanda
        (lazy-load) — a fila compartilhada (_MaterializeQueue) espaça a
        criação entre todas as TerminalArea pra evitar rajada de
        QWebEngineView simultâneas. Disparado pelo timer coalescente de
        _on_bar_current_changed."""
        if not _area_is_active(self):
            return  # área de workspace não-exposto: materializa ao ativar
        w = self._stack.currentWidget()
        if isinstance(w, TerminalWidget):
            _get_materialize_queue().enqueue(self, w)

    def focus_active_console(self) -> None:
        """Traz o console ativo pro topo do z-order (StackAll) e manda o foco
        pra webview, pra digitação cair no console certo sem clique do mouse.

        setFocus() só é chamado numa QWebEngineView depois que o bridge JS
        sinaliza pronto (_bridge_ready). Focar uma view recém-criada, ainda
        inicializando seu QQuickWindow interno, reentra no resolvedor de
        wrapper do PySide e derruba o processo (SIGSEGV em
        PySide::getWrapperForQObject) — reproduzido ao restaurar várias
        sessões de uma vez, cada uma materializando e recebendo foco em
        sequência."""
        w = self._stack.currentWidget()
        if w is None:
            return
        # StackAll deixa todas visíveis; garante a ativa no topo do z-order.
        w.raise_()
        view = getattr(w, "view", None)
        if view is None:
            w.setFocus()
            return
        if getattr(w, "_bridge_ready", False):
            view.setFocus()
        else:
            self._focus_when_ready(w)

    def _focus_when_ready(self, w: TerminalWidget) -> None:
        """Adia o setFocus() pra quando o bridge JS da view sinalizar pronto
        (ver focus_active_console). Reconfere se `w` ainda é o console ativo
        na hora, pra não focar uma aba que o usuário já trocou."""
        bridge = getattr(w, "bridge", None)
        if bridge is None:
            return

        def _on_ready() -> None:
            try:
                bridge.ready.disconnect(_on_ready)
            except RuntimeError:
                return  # bridge/console já destruído (fechou antes do ready)
            try:
                if self._stack.currentWidget() is w:
                    view = getattr(w, "view", None)
                    if view is not None:
                        view.setFocus()
            except RuntimeError:
                pass  # widget fechado entre o disparo do sinal e o setFocus

        bridge.ready.connect(_on_ready)

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

    def add_terminal(self, title: str, *, make_current: bool = True) -> TerminalWidget:
        """`make_current=False` (restore de boot): adiciona a aba sem
        promovê-la a current — não dispara materialização de WebView nem
        rouba o foco. Obs.: a PRIMEIRA aba de uma área vazia sempre vira
        current (comportamento do QTabBar), o que é desejado."""
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
            lambda code, w=widget: self.tab_session_exited.emit(tab_uid_of(w), code)
        )
        idx = self._stack.addWidget(widget)
        self._bar.insertTab(idx, title)
        if make_current:
            self._set_current_index(idx)
        widget.setProperty("_base_title", title)
        # Texto inicial já com `#N` (mesmo formato do sidebar).
        self._bar.setTabText(idx, f"✓ {self._compute_tab_display(widget)}")
        self._apply_tab_color(idx, widget)
        self._refresh_tab_bar_visibility()
        # Emite estado inicial
        self.tab_activity_changed.emit(tab_uid_of(widget), title, "", False, False, False)
        return widget

    def _compute_tab_display(self, widget: TerminalWidget) -> str:
        """Mesmo formato `#N Title` usado no sidebar: N é a posição entre
        os irmãos ordenados por `tab_uid` crescente (mais antigo = #1).
        Title é o `effective_title()` do widget — espelha custom_name /
        session_preview / base_title, então renomear via sidebar reflete
        aqui imediatamente."""
        sibling_ids: list[int] = []
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if w is not None:
                sibling_ids.append(tab_uid_of(w))
        sibling_ids.sort()
        wid = tab_uid_of(widget)
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
            tab_uid_of(widget),
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
        tab_id = tab_uid_of(widget) if widget is not None else 0
        if isinstance(widget, TerminalWidget):
            widget.terminate()
            widget.release_session_claim()
            note_view_destroyed_externally(widget)
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

    def remove_terminal(self, widget: TerminalWidget) -> str:
        """Remove widget from this area without deleting it (for transfer to another area).
        Returns the tab bar text. Disconnects bound-method signals; lambda slots
        become no-ops after widget leaves the stack (indexOf returns -1)."""
        idx = self._stack.indexOf(widget)
        if idx < 0:
            return ""
        text = self._bar.tabText(idx)
        try:
            widget.running_changed.disconnect(self._on_running_changed)
        except RuntimeError:
            pass
        try:
            widget.session_exited.disconnect()
        except RuntimeError:
            pass
        self._bar.removeTab(idx)
        self._stack.removeWidget(widget)
        if widget.is_running() and self._running_count > 0:
            self._running_count -= 1
            self.running_count_changed.emit(self._running_count)
        self._refresh_tab_bar_visibility()
        self._refresh_all_tab_texts()
        return text

    def adopt_terminal(self, widget: TerminalWidget, title: str = "") -> None:
        """Add an existing TerminalWidget (from another area) to this one."""
        if not title:
            title = widget.property("_base_title") or ""
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
            lambda code, w=widget: self.tab_session_exited.emit(tab_uid_of(w), code)
        )
        idx = self._stack.addWidget(widget)
        self._bar.insertTab(idx, title)
        if widget.is_running():
            self._running_count += 1
            self.running_count_changed.emit(self._running_count)
        self._set_current_index(idx)
        self._refresh_tab_bar_visibility()
        self._refresh_all_tab_texts()

    def close_all(self) -> None:
        while self._bar.count():
            self._close_tab(0)
