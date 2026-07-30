"""Tab bar global de consoles — vive na top bar (estilo Orca: tab = sessão).

Espelha e CONTROLA — nunca possui — os consoles de todos os workspaces.
Constrói-se 100% pelos sinais que o TerminalCoordinator já emite
(`tab_activity_changed` com workspace_id, `tab_removed`): uma tab nova
aparece na primeira atividade de um tab_uid desconhecido; título, cor de
status e tooltip acompanham as atualizações (coalescidas num timer de
0ms pra aguentar a rajada do boot). Clique/fechar emitem sinais que a
MainWindow traduz pro fluxo existente (terminal_host + TerminalArea +
sidebar) — nada de ownership de widget aqui.
"""

import logging
from collections import deque

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTabBar,
    QWidget,
)

from . import theme
from .icons import ic
from .terminal_child_widget import (
    STATE_AWAITING,
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_WORKING,
)

log = logging.getLogger(__name__)

# Mesma paleta de status das abas internas do TerminalArea / sidebar.
_STATUS_COLOR = {
    STATE_WORKING: theme.WARNING,
    STATE_AWAITING: theme.WAITING,
    STATE_IDLE: theme.DANGER,
    STATE_DONE: theme.SUCCESS,
    STATE_ERROR: theme.DANGER,
}

_TABBAR_QSS = (
    f"QTabBar {{ background: transparent; }}"
    f"QTabBar::tab {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FADED};"
    f"  padding: 5px 10px;"
    f"  border: 0;"
    f"  border-bottom: 2px solid transparent;"
    f"  font-size: {theme.FONT_MD}px;"
    f"  min-height: 20px;"
    f"}}"
    f"QTabBar::tab:hover {{ color: {theme.TEXT_PRIMARY}; }}"
    f"QTabBar::tab:selected {{"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  border-bottom: 2px solid {theme.PRIMARY};"
    f"}}"
    f"QTabBar::close-button {{ subcontrol-position: right; }}"
    f"QTabBar QToolButton {{"
    f"  background: transparent; border: 0; color: {theme.TEXT_FAINT};"
    f"}}"
    f"QTabBar QToolButton:hover {{ color: {theme.TEXT_PRIMARY}; }}"
)

_NAV_BTN_QSS = (
    "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
    f"QPushButton:hover {{ background: {theme.BG_SURFACE}; }}"
    f"QPushButton:disabled {{ background: transparent; }}"
)


def _dot_pixmap(color: str, d: int = 8) -> QIcon:
    """Bolinha de status usada como ícone da tab."""
    pm = QPixmap(d, d)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(0, 0, d, d)
    p.end()
    return QIcon(pm)


class GlobalConsoleTabBar(QWidget):
    """◀ ▶ + QTabBar de todos os consoles + botão "+"."""

    # tab_uid do console que o usuário quer ativar/fechar
    tab_activate_requested = Signal("qint64")
    tab_close_requested = Signal("qint64")
    # Menu do "+": novo console no workspace ativo / shell / IA / hack
    new_console_requested = Signal()
    open_terminal_requested = Signal()
    open_claude_no_ctx_requested = Signal()
    hack_app_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # tab_uid -> dict(ws_id, title, status, running, needs_decision)
        self._tabs: dict[int, dict] = {}
        self._order: list[int] = []
        self._dirty = False
        # Resolve nome do workspace pra tooltip/sufixo (injetado pela
        # MainWindow; None → sem sufixo).
        self._ws_name_resolver = None
        # Histórico MRU de ativações pros botões ◀ ▶.
        self._history: deque[int] = deque(maxlen=64)
        self._history_pos = -1
        self._navigating = False
        # Guarda anti-loop: mudanças programáticas do índice não devem
        # re-emitir tab_activate_requested.
        self._syncing = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        self._back_btn = QPushButton()
        self._back_btn.setIcon(ic("fa5s.chevron-left", color=theme.TEXT_FAINT))
        self._back_btn.setIconSize(QSize(11, 11))
        self._back_btn.setFixedSize(24, 26)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setToolTip("Console anterior (histórico)")
        self._back_btn.setStyleSheet(_NAV_BTN_QSS)
        self._back_btn.clicked.connect(self._go_back)
        row.addWidget(self._back_btn)

        self._fwd_btn = QPushButton()
        self._fwd_btn.setIcon(ic("fa5s.chevron-right", color=theme.TEXT_FAINT))
        self._fwd_btn.setIconSize(QSize(11, 11))
        self._fwd_btn.setFixedSize(24, 26)
        self._fwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fwd_btn.setToolTip("Console seguinte (histórico)")
        self._fwd_btn.setStyleSheet(_NAV_BTN_QSS)
        self._fwd_btn.clicked.connect(self._go_forward)
        row.addWidget(self._fwd_btn)

        self._bar = QTabBar()
        self._bar.setTabsClosable(True)
        self._bar.setMovable(False)
        self._bar.setDocumentMode(True)
        self._bar.setDrawBase(False)
        self._bar.setExpanding(False)
        self._bar.setUsesScrollButtons(True)
        self._bar.setElideMode(Qt.TextElideMode.ElideRight)
        self._bar.setStyleSheet(_TABBAR_QSS)
        self._bar.tabBarClicked.connect(self._on_tab_clicked)
        self._bar.tabCloseRequested.connect(self._on_close_requested)
        row.addWidget(self._bar, stretch=1)

        self._plus_btn = QPushButton()
        self._plus_btn.setIcon(ic("fa5s.plus", color=theme.TEXT_FAINT))
        self._plus_btn.setIconSize(QSize(11, 11))
        self._plus_btn.setFixedSize(26, 26)
        self._plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus_btn.setToolTip(
            "Novo console no workspace ativo (segure pra mais opções)"
        )
        self._plus_btn.setStyleSheet(_NAV_BTN_QSS)
        self._plus_btn.clicked.connect(self.new_console_requested)
        self._plus_btn.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._plus_btn.customContextMenuRequested.connect(
            lambda _p: self._open_plus_menu()
        )
        row.addWidget(self._plus_btn)

        # Coalescedor: rajadas de tab_activity_changed (boot com N sessões)
        # viram UM refresh visual.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._refresh)

        self._update_nav_buttons()

    # ------------------------------------------------------------------
    # Entrada de dados (sinais do TerminalCoordinator)

    def set_workspace_name_resolver(self, fn) -> None:
        """fn(ws_id) -> str | None. Usado em tooltip e sufixo da tab."""
        self._ws_name_resolver = fn

    def on_tab_activity(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,  # noqa: ARG002 — assinatura do sinal
        is_running: bool,
        workspace_id: str,
        needs_decision: bool,
    ) -> None:
        info = self._tabs.get(tab_id)
        if info is None:
            info = {"ws_id": workspace_id}
            self._tabs[tab_id] = info
            self._order.append(tab_id)
        info.update(
            title=title or info.get("title", ""),
            status=status,
            running=is_running,
            needs_decision=needs_decision,
            ws_id=workspace_id or info.get("ws_id", ""),
        )
        self._schedule_refresh()

    def on_tab_removed(self, tab_id: int) -> None:
        if tab_id in self._tabs:
            del self._tabs[tab_id]
            self._order = [u for u in self._order if u != tab_id]
            # Expurga do histórico MRU.
            self._history = deque(
                (u for u in self._history if u != tab_id), maxlen=64
            )
            self._history_pos = min(self._history_pos, len(self._history) - 1)
            self._schedule_refresh()

    def set_active_uid(self, uid: int) -> None:
        """Marca a tab do console ativo (chamado pela MainWindow quando o
        console/área atual muda por qualquer caminho). Alimenta o MRU."""
        if uid and uid in self._tabs and not self._navigating:
            # Trunca o "futuro" do histórico ao navegar por clique normal.
            while len(self._history) - 1 > self._history_pos:
                self._history.pop()
            if not self._history or self._history[-1] != uid:
                self._history.append(uid)
            self._history_pos = len(self._history) - 1
        self._schedule_refresh()
        self._update_nav_buttons()

    def active_uid(self) -> int:
        idx = self._bar.currentIndex()
        if idx < 0:
            return 0
        return int(self._bar.tabData(idx) or 0)

    # ------------------------------------------------------------------

    def _schedule_refresh(self) -> None:
        self._dirty = True
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh(self) -> None:
        """Reconstrói/atualiza as tabs in-place a partir do modelo."""
        if not self._dirty:
            return
        self._dirty = False
        self._syncing = True
        try:
            # Ajusta contagem.
            while self._bar.count() > len(self._order):
                self._bar.removeTab(self._bar.count() - 1)
            while self._bar.count() < len(self._order):
                self._bar.addTab("")
            active_uid = self._current_active_uid()
            for i, uid in enumerate(self._order):
                info = self._tabs.get(uid, {})
                self._bar.setTabData(i, uid)
                title = info.get("title") or "console"
                ws_name = self._resolve_ws_name(info.get("ws_id", ""))
                self._bar.setTabText(i, title)
                tip = f"{title} · {ws_name}" if ws_name else title
                self._bar.setTabToolTip(i, tip)
                color = self._status_color(info)
                self._bar.setTabIcon(i, _dot_pixmap(color))
                if uid == active_uid:
                    self._bar.setCurrentIndex(i)
        finally:
            self._syncing = False

    def _current_active_uid(self) -> int:
        if self._history and 0 <= self._history_pos < len(self._history):
            return self._history[self._history_pos]
        return self.active_uid()

    def _resolve_ws_name(self, ws_id: str) -> str:
        if not ws_id or self._ws_name_resolver is None:
            return ""
        try:
            return self._ws_name_resolver(ws_id) or ""
        except Exception:
            return ""

    def _status_color(self, info: dict) -> str:
        if not info.get("running"):
            return theme.TEXT_FAINT
        if info.get("needs_decision"):
            return theme.WAITING
        return _STATUS_COLOR.get(info.get("status", ""), theme.TEXT_FAINT)

    # ------------------------------------------------------------------
    # Interação

    def _on_tab_clicked(self, idx: int) -> None:
        if self._syncing or idx < 0:
            return
        uid = int(self._bar.tabData(idx) or 0)
        if uid:
            self.tab_activate_requested.emit(uid)

    def _on_close_requested(self, idx: int) -> None:
        uid = int(self._bar.tabData(idx) or 0)
        if uid:
            self.tab_close_requested.emit(uid)

    def _open_plus_menu(self) -> None:
        menu = QMenu(self._plus_btn)
        menu.addAction("Novo console no workspace ativo").triggered.connect(
            self.new_console_requested
        )
        menu.addSeparator()
        menu.addAction("Abrir shell em $HOME").triggered.connect(
            self.open_terminal_requested
        )
        menu.addAction("Abrir agente sem contexto").triggered.connect(
            self.open_claude_no_ctx_requested
        )
        menu.addAction("Hack no claude-workspaces").triggered.connect(
            self.hack_app_requested
        )
        menu.exec(self._plus_btn.mapToGlobal(self._plus_btn.rect().bottomLeft()))

    def _go_back(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self._navigate_to(self._history[self._history_pos])

    def _go_forward(self) -> None:
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._navigate_to(self._history[self._history_pos])

    def _navigate_to(self, uid: int) -> None:
        self._navigating = True
        try:
            self.tab_activate_requested.emit(uid)
        finally:
            self._navigating = False
        self._update_nav_buttons()
        self._schedule_refresh()

    def _update_nav_buttons(self) -> None:
        self._back_btn.setEnabled(self._history_pos > 0)
        self._fwd_btn.setEnabled(
            self._history_pos < len(self._history) - 1
        )
