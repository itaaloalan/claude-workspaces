"""Coluna vertical de ícones à esquerda — navega entre views top-level
(Workspaces, Catálogo, Hooks, MCP, Settings).

Pattern inspirado no VS Code activity bar. Largura fixa de ~52px,
botões grandes pra clicar fácil. Botão ativo destacado.
"""


from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

VIEW_WORKSPACES = "workspaces"
VIEW_CATALOG = "catalog"
VIEW_HOOKS = "hooks"
VIEW_MCP = "mcp"
VIEW_PLUGINS = "plugins"
VIEW_APPS = "apps"
VIEW_SETTINGS = "settings"


_BUTTON_CSS = (
    "QPushButton {"
    "  background: transparent;"
    "  color: #888;"
    "  border: none;"
    "  border-left: 2px solid transparent;"
    "  padding: 10px 0;"
    "  font-size: 18px;"
    "  text-align: center;"
    "}"
    "QPushButton:hover { color: #d4d4d4; background: #2a2a2a; }"
    "QPushButton:checked {"
    "  color: #6aa9e0;"
    "  background: #232323;"
    "  border-left: 2px solid #6aa9e0;"
    "}"
)


class ActivityBar(QWidget):
    view_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(48)
        self.setStyleSheet("background: #1a1a1a; border-right: 1px solid #2a2a2a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for icon, view_id, tooltip in (
            ("🗂", VIEW_WORKSPACES, "Workspaces (Ctrl+1)"),
            ("📚", VIEW_CATALOG, "Catálogo de skills/agents/commands (Ctrl+2)"),
            ("🪝", VIEW_HOOKS, "Hooks (Ctrl+3)"),
            ("🔌", VIEW_MCP, "MCP servers (Ctrl+4)"),
            ("🧩", VIEW_PLUGINS, "Plugins (Ctrl+5)"),
            ("🧰", VIEW_APPS, "Apps auxiliares (Ctrl+6)"),
        ):
            btn = self._make_button(icon, view_id, tooltip)
            layout.addWidget(btn)
            self._buttons[view_id] = btn
            self._group.addButton(btn)

        layout.addStretch()

        # Settings sempre no fim, separado
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a; margin: 0 8px;")
        layout.addWidget(sep)

        settings_btn = self._make_button("⚙", VIEW_SETTINGS, "Settings")
        layout.addWidget(settings_btn)
        self._buttons[VIEW_SETTINGS] = settings_btn
        self._group.addButton(settings_btn)

        # Default ativo: Workspaces
        self._buttons[VIEW_WORKSPACES].setChecked(True)

    def _make_button(self, icon: str, view_id: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setFixedSize(48, 48)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_BUTTON_CSS)
        btn.setToolTip(tooltip)
        btn.setProperty("view_id", view_id)
        btn.toggled.connect(
            lambda checked, vid=view_id: self.view_changed.emit(vid) if checked else None
        )
        return btn

    def set_active(self, view_id: str) -> None:
        """Marca um botão como ativo sem emitir signal (programmatic)."""
        btn = self._buttons.get(view_id)
        if btn and not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def activate(self, view_id: str) -> None:
        """Marca um botão como ativo E dispara o view_changed."""
        btn = self._buttons.get(view_id)
        if btn:
            btn.setChecked(True)
            # toggled signal já emite view_changed via _make_button
