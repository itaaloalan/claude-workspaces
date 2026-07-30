"""Janela frameless opt-in (settings.frameless_window).

A decoração do sistema some e a TopBar vira a barra de título: arrastar
em área vazia move a janela via `startSystemMove()` (o KWin cuida de
snap/quarter-tiling em X11 e Wayland), duplo-clique maximiza/restaura,
e os controles min/max/close entram à direita da barra. O resize é por
hit-test de margem (6px) nas bordas da própria janela →
`startSystemResize(edges)`.

Redes de segurança no KDE: Meta+drag (mover) e Meta+right-drag (resize)
do KWin continuam funcionando mesmo frameless; a flag desligada volta à
decoração nativa sem tocar em código.
"""

import logging

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from . import theme
from .icons import ic

log = logging.getLogger(__name__)

RESIZE_MARGIN = 6

_CTRL_BTN_QSS = (
    "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
    f"QPushButton:hover {{ background: {theme.BG_SURFACE}; }}"
)
_CLOSE_BTN_QSS = (
    "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
    f"QPushButton:hover {{ background: {theme.DANGER}; }}"
)


class WindowControls(QWidget):
    """Botões min / max-restore / close pro modo frameless."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 0, 0)
        row.setSpacing(2)

        self._min_btn = QPushButton()
        self._min_btn.setIcon(ic("ph.minus", color=theme.TEXT_FADED))
        self._min_btn.setToolTip("Minimizar")
        self._min_btn.clicked.connect(window.showMinimized)

        self._max_btn = QPushButton()
        self._max_btn.setToolTip("Maximizar / restaurar")
        self._max_btn.clicked.connect(self._toggle_maximized)

        self._close_btn = QPushButton()
        self._close_btn.setIcon(ic("ph.x", color=theme.TEXT_FADED))
        self._close_btn.setToolTip("Fechar")
        self._close_btn.clicked.connect(window.close)
        self._close_btn.setStyleSheet(_CLOSE_BTN_QSS)

        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.setFixedSize(30, 28)
            btn.setIconSize(QSize(12, 12))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if btn is not self._close_btn:
                btn.setStyleSheet(_CTRL_BTN_QSS)
            row.addWidget(btn)

        self._refresh_max_icon()
        window.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._window and event.type() == QEvent.Type.WindowStateChange:
            self._refresh_max_icon()
        return False

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _refresh_max_icon(self) -> None:
        name = (
            "ph.copy"
            if self._window.isMaximized()
            else "ph.square"
        )
        self._max_btn.setIcon(ic(name, color=theme.TEXT_FADED))


class TitleBarDragFilter(QObject):
    """Instalado na TopBar: arrastar em área vazia move a janela
    (startSystemMove → o compositor cuida de snap/tiling); duplo-clique
    maximiza/restaura."""

    def __init__(self, window, top_bar: QWidget) -> None:
        super().__init__(top_bar)
        self._window = window
        self._bar = top_bar
        top_bar.installEventFilter(self)

    def _is_empty_area(self, pos) -> bool:
        child = self._bar.childAt(pos)
        # Área vazia ou widgets não-interativos (labels). QTabBar/botões/
        # inputs tratam o próprio clique.
        if child is None:
            return True
        from PySide6.QtWidgets import QAbstractButton, QLineEdit, QTabBar
        w = child
        while w is not None and w is not self._bar:
            if isinstance(w, (QAbstractButton, QLineEdit, QTabBar)):
                return False
            w = w.parentWidget()
        return True

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is not self._bar:
            return False
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._is_empty_area(event.position().toPoint())
            ):
                handle = self._window.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                    return True
        elif et == QEvent.Type.MouseButtonDblClick:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._is_empty_area(event.position().toPoint())
            ):
                if self._window.isMaximized():
                    self._window.showNormal()
                else:
                    self._window.showMaximized()
                return True
        return False


class ResizeEdgeFilter(QObject):
    """Hit-test de margem (6px) nas bordas da janela frameless →
    cursor de resize + startSystemResize(edges). Desativado quando
    maximizado."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        window.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        window.installEventFilter(self)

    def _edges_at(self, pos) -> Qt.Edge:
        if self._window.isMaximized() or self._window.isFullScreen():
            return Qt.Edge(0)
        w, h = self._window.width(), self._window.height()
        m = RESIZE_MARGIN
        edges = Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    _CURSORS = {
        Qt.Edge.LeftEdge.value: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.RightEdge.value: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge.value: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.BottomEdge.value: Qt.CursorShape.SizeVerCursor,
        (Qt.Edge.LeftEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeFDiagCursor,
        (Qt.Edge.RightEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeFDiagCursor,
        (Qt.Edge.RightEdge | Qt.Edge.TopEdge).value: Qt.CursorShape.SizeBDiagCursor,
        (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge).value: Qt.CursorShape.SizeBDiagCursor,
    }

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is not self._window:
            return False
        et = event.type()
        if et in (QEvent.Type.HoverMove, QEvent.Type.HoverEnter):
            edges = self._edges_at(event.position().toPoint())
            cursor = self._CURSORS.get(edges.value if hasattr(edges, 'value') else int(edges))
            if cursor is not None:
                self._window.setCursor(cursor)
            else:
                self._window.unsetCursor()
        elif et == QEvent.Type.HoverLeave:
            self._window.unsetCursor()
        elif et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                edges = self._edges_at(event.position().toPoint())
                if edges:
                    handle = self._window.windowHandle()
                    if handle is not None:
                        handle.startSystemResize(edges)
                        return True
        return False


def enable_frameless(window, top_bar) -> WindowControls:
    """Ativa o modo frameless: flag na janela, moldura de 1px, drag na
    TopBar, hit-test de resize e controles min/max/close (retornados pra
    quem chamar posicionar na barra). Chamar ANTES do show()."""
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    # Moldura de 1px da própria janela — garante que o pixel da borda é
    # nosso (hit-test de resize) e não de uma webview interna.
    window.setStyleSheet(
        window.styleSheet()
        + f"\nQMainWindow {{ border: 1px solid {theme.BORDER}; }}"
    )
    TitleBarDragFilter(window, top_bar)
    ResizeEdgeFilter(window)
    controls = WindowControls(window)
    log.info("modo frameless ativo (settings.frameless_window)")
    return controls
