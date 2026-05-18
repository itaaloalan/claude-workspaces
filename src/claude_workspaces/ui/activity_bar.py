"""Coluna vertical de ícones à esquerda — navega entre views top-level
(Workspaces, Catálogo, Hooks, MCP, Settings).

Pattern inspirado no VS Code activity bar. Largura fixa de ~52px,
botões grandes pra clicar fácil. Botão ativo destacado.

Ícones: glyphs Unicode monocromáticos (não-emoji) com presentation
selector U+FE0E pra evitar renderização colorida tipo "infantil" em
algumas plataformas. Família de fonte forçada pra um fallback técnico
quando disponível.
"""


from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

VIEW_WORKSPACES = "workspaces"
VIEW_CATALOG = "catalog"
VIEW_HOOKS = "hooks"
VIEW_MCP = "mcp"
VIEW_PLUGINS = "plugins"
VIEW_APPS = "apps"
VIEW_SETTINGS = "settings"

# U+FE0E força "text presentation" no glyph anterior — evita render emoji
_VS15 = "︎"

_ICON_FONT_STACK = (
    '"Symbola", "DejaVu Sans Mono", "Noto Sans Symbols 2",'
    ' "Segoe UI Symbol", monospace'
)

_BUTTON_CSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: none;"
    f"  border-left: 2px solid transparent;"
    f"  padding: 10px 0;"
    f"  font-family: {_ICON_FONT_STACK};"
    f"  font-size: 18px;"
    f"  font-weight: 500;"
    f"  text-align: center;"
    f"}}"
    f"QPushButton:hover {{"
    f"  color: {theme.TEXT_MUTED};"
    f"  background: {theme.BG_SURFACE};"
    f"}}"
    f"QPushButton:checked {{"
    f"  color: {theme.TEXT_LINK};"
    f"  background: {theme.BG_DARKER};"
    f"  border-left: 2px solid {theme.TEXT_LINK};"
    f"}}"
)


class ActivityBar(QWidget):
    view_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(48)
        self.setStyleSheet(
            f"background: {theme.BG_PANEL};"
            f" border-right: 1px solid {theme.BORDER};"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        # Glyphs escolhidos pra parecer ícones técnicos (não emojis):
        #   ❒  folha empilhada       → Workspaces (várias pastas)
        #   ☰  três linhas           → Catálogo (lista de skills)
        #   ⚓  âncora                → Hooks (gancho)
        #   ⌬  benzeno               → MCP (rede/servers)
        #   ◆  diamante              → Plugins (extensão)
        #   ▣  quadrado preenchido   → Apps (tile)
        #   ⚙  engrenagem            → Settings
        for icon, view_id, tooltip in (
            ("❒", VIEW_WORKSPACES, "Workspaces (Ctrl+Shift+1)"),
            ("☰", VIEW_CATALOG, "Catálogo de skills/agents/commands (Ctrl+Shift+2)"),
            ("⚓", VIEW_HOOKS, "Hooks (Ctrl+Shift+3)"),
            ("⌬", VIEW_MCP, "MCP servers (Ctrl+Shift+4)"),
            ("◆", VIEW_PLUGINS, "Plugins (Ctrl+Shift+5)"),
            ("▣", VIEW_APPS, "Apps auxiliares (Ctrl+Shift+6)"),
        ):
            btn = self._make_button(icon + _VS15, view_id, tooltip)
            layout.addWidget(btn)
            self._buttons[view_id] = btn
            self._group.addButton(btn)

        layout.addStretch()

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER}; margin: 0 10px;")
        layout.addWidget(sep)

        settings_btn = self._make_button("⚙" + _VS15, VIEW_SETTINGS, "Settings")
        layout.addWidget(settings_btn)
        self._buttons[VIEW_SETTINGS] = settings_btn
        self._group.addButton(settings_btn)

        # Default ativo: Workspaces
        self._buttons[VIEW_WORKSPACES].setChecked(True)

    def _make_button(self, icon: str, view_id: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setFixedSize(48, 44)
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
