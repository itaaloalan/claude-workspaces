"""Navegação principal no topo da sidebar — linha compacta de ícones.

Uma row horizontal (~30px) com um botão-ícone por view (Workspaces,
Catálogo, Hooks, MCP, Plugins, Apps) — o formato de linhas com label
ocupava ~175px verticais antes da lista de projetos. Tooltip carrega o
nome + atalho; badges de contagem ficam ancorados no canto do ícone.
API espelha a da antiga ActivityBar (view_changed / set_active /
activate / set_badge) — MainWindow e shortcuts não mudam.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from . import theme
from .icons import ic

VIEW_WORKSPACES = "workspaces"
VIEW_CATALOG = "catalog"
VIEW_HOOKS = "hooks"
VIEW_MCP = "mcp"
VIEW_PLUGINS = "plugins"
VIEW_APPS = "apps"
VIEW_SETTINGS = "settings"

_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  border: 0;"
    f"  border-radius: {theme.RADIUS_MD}px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.PRIMARY_HOVER_BG};"
    f"}}"
    f"QPushButton:checked {{"
    f"  background: {theme.PRIMARY_SELECTION_BG};"
    f"}}"
)

_BADGE_QSS = (
    f"QLabel {{"
    f"  background: rgba(90, 90, 90, 235);"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  border-radius: 6px;"
    f"  padding: 0px 3px;"
    f"  font-size: 8px;"
    f"  font-weight: 600;"
    f"}}"
)


class _NavIconButton(QPushButton):
    """Botão-ícone com badge de contagem ancorado no canto superior
    direito (child posicionado à mão — QSS não posiciona overlay)."""

    def __init__(
        self, icon: str, label: str, tooltip: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self._label = label
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tooltip)
        self.setFixedSize(32, 28)
        self.setStyleSheet(_BTN_QSS)
        self._paint_icon()
        self.toggled.connect(lambda _c: self._paint_icon())

        self._badge = QLabel("", self)
        self._badge.setStyleSheet(_BADGE_QSS)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setVisible(False)

    def _paint_icon(self) -> None:
        from PySide6.QtCore import QSize
        color = theme.TEXT_PRIMARY if self.isChecked() else theme.TEXT_FADED
        self.setIcon(ic(self._icon_name, color=color))
        self.setIconSize(QSize(16, 16))

    def _place_badge(self) -> None:
        self._badge.adjustSize()
        w = max(self._badge.width(), 12)
        h = max(self._badge.height(), 12)
        # Canto superior direito, levemente pra dentro.
        self._badge.setGeometry(self.width() - w - 1, 0, w, h)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._badge.isVisible():
            self._place_badge()

    def set_badge(self, text: str, tooltip: str | None = None) -> None:
        if not text:
            self._badge.setVisible(False)
            self._badge.setText("")
            self._badge.setToolTip("")
            return
        self._badge.setText(text)
        self._badge.setToolTip(tooltip or "")
        self._badge.setVisible(True)
        self._place_badge()
        self._badge.raise_()


class SidebarNav(QWidget):
    view_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(30)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)

        self._buttons: dict[str, _NavIconButton] = {}
        for icon, view_id, label, tooltip in (
            ("ph.squares-four", VIEW_WORKSPACES, "Workspaces",
                "Workspaces (Ctrl+Shift+1)"),
            ("ph.book", VIEW_CATALOG, "Catálogo",
                "Catálogo de skills/agents/commands (Ctrl+Shift+2)"),
            ("ph.anchor", VIEW_HOOKS, "Hooks", "Hooks (Ctrl+Shift+3)"),
            ("ph.share-network", VIEW_MCP, "MCP", "MCP servers (Ctrl+Shift+4)"),
            ("ph.puzzle-piece", VIEW_PLUGINS, "Plugins",
                "Plugins (Ctrl+Shift+5)"),
            ("ph.grid-four", VIEW_APPS, "Apps",
                "Apps auxiliares (Ctrl+Shift+6)"),
        ):
            btn = _NavIconButton(icon, label, tooltip)
            btn.clicked.connect(lambda _c=False, vid=view_id: self._on_clicked(vid))
            h.addWidget(btn)
            self._buttons[view_id] = btn
        h.addStretch(1)

        self._buttons[VIEW_WORKSPACES].setChecked(True)

    def _on_clicked(self, view_id: str) -> None:
        for vid, b in self._buttons.items():
            b.setChecked(vid == view_id)
        self.view_changed.emit(view_id)

    def set_active(self, view_id: str) -> None:
        """Marca uma view como ativa sem emitir signal (programmatic).
        `settings` não tem botão próprio — desmarca tudo."""
        for vid, b in self._buttons.items():
            b.setChecked(vid == view_id)

    def activate(self, view_id: str) -> None:
        """Marca como ativa E dispara o view_changed."""
        if view_id in self._buttons:
            self._on_clicked(view_id)

    def set_badge(
        self, view_id: str, text: str, tooltip: str | None = None
    ) -> None:
        btn = self._buttons.get(view_id)
        if btn is not None:
            btn.set_badge(text, tooltip)
