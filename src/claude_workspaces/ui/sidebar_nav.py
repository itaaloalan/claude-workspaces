"""Navegação principal no topo da sidebar — estilo Orca.

Linhas flat full-width com ícone + label (Workspaces, Catálogo, Hooks,
MCP, Plugins, Apps). Substitui a ActivityBar vertical de 52px: a view
ativa ganha fundo sutil arredondado; badges de contagem aparecem à
direita da linha. API espelha a da ActivityBar (view_changed /
set_active / activate / set_badge) pra troca 1:1 na MainWindow.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .icons import ic

VIEW_WORKSPACES = "workspaces"
VIEW_CATALOG = "catalog"
VIEW_HOOKS = "hooks"
VIEW_MCP = "mcp"
VIEW_PLUGINS = "plugins"
VIEW_APPS = "apps"
VIEW_SETTINGS = "settings"

_ROW_QSS = (
    f"QFrame#NavRow {{"
    f"  background: transparent;"
    f"  border: 0;"
    f"  border-radius: {theme.RADIUS_MD}px;"
    f"}}"
    f"QFrame#NavRow:hover {{"
    f"  background: {theme.PRIMARY_HOVER_BG};"
    f"}}"
    f"QFrame#NavRow[nav_checked=\"true\"] {{"
    f"  background: {theme.PRIMARY_SELECTION_BG};"
    f"}}"
    f"QFrame#NavRow QLabel#NavLabel {{"
    f"  color: {theme.TEXT_FADED};"
    f"  font-size: {theme.FONT_MD}px;"
    f"  background: transparent;"
    f"}}"
    f"QFrame#NavRow:hover QLabel#NavLabel {{"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    f"QFrame#NavRow[nav_checked=\"true\"] QLabel#NavLabel {{"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  font-weight: 500;"
    f"}}"
    f"QFrame#NavRow QLabel#NavBadge {{"
    f"  background: rgba(255, 255, 255, 30);"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  border-radius: 7px;"
    f"  padding: 0px 5px;"
    f"  font-size: 9px;"
    f"  font-weight: 600;"
    f"  min-width: 14px;"
    f"  min-height: 14px;"
    f"  max-height: 14px;"
    f"}}"
)


class _NavRow(QFrame):
    """Linha de navegação: ícone + label + badge opcional."""

    clicked = Signal()

    def __init__(
        self, icon: str, label: str, tooltip: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NavRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tooltip)
        self.setFixedHeight(28)
        self._checked = False
        self.setProperty("nav_checked", "false")
        self._icon_name = icon

        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(8)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setStyleSheet("background: transparent;")
        self._paint_icon()
        h.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._text_label = QLabel(label)
        self._text_label.setObjectName("NavLabel")
        h.addWidget(self._text_label, 1)

        self._badge_label = QLabel("")
        self._badge_label.setObjectName("NavBadge")
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_label.setVisible(False)
        h.addWidget(self._badge_label, 0, Qt.AlignmentFlag.AlignVCenter)

    def _paint_icon(self) -> None:
        color = theme.TEXT_PRIMARY if self._checked else theme.TEXT_FADED
        self._icon_label.setPixmap(
            ic(self._icon_name, color=color).pixmap(QSize(15, 15))
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if self._checked == value:
            return
        self._checked = value
        self.setProperty("nav_checked", "true" if value else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._paint_icon()

    def set_badge(self, text: str, tooltip: str | None = None) -> None:
        if not text:
            self._badge_label.setVisible(False)
            self._badge_label.setText("")
            self._badge_label.setToolTip("")
            return
        self._badge_label.setText(text)
        self._badge_label.setToolTip(tooltip or "")
        self._badge_label.setVisible(True)


class SidebarNav(QWidget):
    view_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(_ROW_QSS)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        self._buttons: dict[str, _NavRow] = {}
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
            row = _NavRow(icon, label, tooltip)
            row.clicked.connect(lambda vid=view_id: self._on_clicked(vid))
            v.addWidget(row)
            self._buttons[view_id] = row

        self._buttons[VIEW_WORKSPACES].setChecked(True)

    def _on_clicked(self, view_id: str) -> None:
        for vid, b in self._buttons.items():
            b.setChecked(vid == view_id)
        self.view_changed.emit(view_id)

    def set_active(self, view_id: str) -> None:
        """Marca uma view como ativa sem emitir signal (programmatic).
        `settings` não tem linha própria — desmarca tudo."""
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
