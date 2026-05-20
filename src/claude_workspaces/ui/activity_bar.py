"""Coluna vertical de ícones à esquerda — navega entre views top-level
(Workspaces, Catálogo, Hooks, MCP, Settings).

Pattern inspirado no VS Code activity bar. Cada entrada agora tem ícone +
label embaixo e um badge opcional (contador) ao lado do ícone — alimentado
pelo MainWindow via `set_badge(view_id, text, tooltip)`.

Ícones: glyphs Unicode monocromáticos (não-emoji) com presentation
selector U+FE0E pra evitar renderização colorida tipo "infantil" em
algumas plataformas. Família de fonte forçada pra um fallback técnico
quando disponível.
"""


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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

_NAV_BAR_WIDTH = 68

_NAV_BUTTON_QSS = (
    f"QFrame#NavButton {{"
    f"  background: transparent;"
    f"  border-left: 2px solid transparent;"
    f"}}"
    f"QFrame#NavButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"}}"
    f"QFrame#NavButton[nav_checked=\"true\"] {{"
    f"  background: {theme.BG_DARKER};"
    f"  border-left: 2px solid {theme.TEXT_LINK};"
    f"}}"
    f"QFrame#NavButton QLabel#NavIcon {{"
    f"  color: {theme.TEXT_FAINT};"
    f"  font-family: {_ICON_FONT_STACK};"
    f"  font-size: 17px;"
    f"  font-weight: 500;"
    f"  background: transparent;"
    f"}}"
    f"QFrame#NavButton:hover QLabel#NavIcon {{"
    f"  color: {theme.TEXT_MUTED};"
    f"}}"
    f"QFrame#NavButton[nav_checked=\"true\"] QLabel#NavIcon {{"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
    f"QFrame#NavButton QLabel#NavLabel {{"
    f"  color: {theme.TEXT_FAINT};"
    f"  font-size: 9px;"
    f"  font-weight: 600;"
    f"  letter-spacing: 0.2px;"
    f"  background: transparent;"
    f"}}"
    f"QFrame#NavButton:hover QLabel#NavLabel {{"
    f"  color: {theme.TEXT_MUTED};"
    f"}}"
    f"QFrame#NavButton[nav_checked=\"true\"] QLabel#NavLabel {{"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    f"QFrame#NavButton QLabel#NavBadge {{"
    f"  background: {theme.PRIMARY};"
    f"  color: {theme.TEXT_BRIGHT};"
    f"  border-radius: 7px;"
    f"  padding: 0px 4px;"
    f"  font-size: 9px;"
    f"  font-weight: 700;"
    f"  min-width: 14px;"
    f"  min-height: 14px;"
    f"  max-height: 14px;"
    f"}}"
)


class _NavButton(QFrame):
    """Botão de navegação com ícone, label e badge opcional.

    Usa QFrame + property `nav_checked` (string "true"/"false") pra que o
    QSS no parent possa reagir ao estado. Mantém API similar a QPushButton
    (checkable): `isChecked()` / `setChecked()` / `clicked` signal.
    """

    clicked = Signal()

    def __init__(
        self, icon: str, label: str, tooltip: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NavButton")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tooltip)
        self._checked = False
        self.setProperty("nav_checked", "false")
        self.setFixedHeight(54)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(2)

        # Linha do ícone com badge (centralizado, badge logo após o ícone)
        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(3)
        icon_row.addStretch(1)
        self._icon_label = QLabel(icon + _VS15)
        self._icon_label.setObjectName("NavIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._badge_label = QLabel("")
        self._badge_label.setObjectName("NavBadge")
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_label.setVisible(False)
        icon_row.addWidget(self._badge_label, 0, Qt.AlignmentFlag.AlignVCenter)
        icon_row.addStretch(1)
        v.addLayout(icon_row)

        self._text_label = QLabel(label)
        self._text_label.setObjectName("NavLabel")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._text_label)

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
        # property dinâmica pra QSS reagir
        self.setProperty("nav_checked", "true" if value else "false")
        # Força re-aplicação do stylesheet
        self.style().unpolish(self)
        self.style().polish(self)

    def set_badge(self, text: str, tooltip: str | None = None) -> None:
        if not text:
            self._badge_label.setVisible(False)
            self._badge_label.setText("")
            self._badge_label.setToolTip("")
            return
        self._badge_label.setText(text)
        self._badge_label.setToolTip(tooltip or "")
        self._badge_label.setVisible(True)


class ActivityBar(QWidget):
    view_changed = Signal(str)
    # Action buttons — ações globais (não trocam view), pra liberar
    # espaço da sidebar de workspaces.
    open_terminal_clicked = Signal()
    open_claude_no_ctx_clicked = Signal()
    hack_app_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_NAV_BAR_WIDTH)
        self.setStyleSheet(
            f"ActivityBar {{ background: {theme.BG_PANEL};"
            f" border-right: 1px solid {theme.BORDER}; }}"
            + _NAV_BUTTON_QSS
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)

        self._buttons: dict[str, _NavButton] = {}

        # Glyphs escolhidos pra parecer ícones técnicos (não emojis):
        #   ▦  grade preenchida      → Workspaces (vários projetos em tiles)
        #   ☰  três linhas           → Catálogo (lista de skills)
        #   ⚓  âncora                → Hooks (gancho)
        #   ⌬  benzeno               → MCP (rede/servers)
        #   ◆  diamante              → Plugins (extensão)
        #   ▣  quadrado preenchido   → Apps (tile)
        #   ⚙  engrenagem            → Settings
        for icon, view_id, label, tooltip in (
            ("▦", VIEW_WORKSPACES, "Workspaces", "Workspaces (Ctrl+Shift+1)"),
            ("☰", VIEW_CATALOG, "Catálogo",
                "Catálogo de skills/agents/commands (Ctrl+Shift+2)"),
            ("⚓", VIEW_HOOKS, "Hooks", "Hooks (Ctrl+Shift+3)"),
            ("⌬", VIEW_MCP, "MCP", "MCP servers (Ctrl+Shift+4)"),
            ("◆", VIEW_PLUGINS, "Plugins", "Plugins (Ctrl+Shift+5)"),
            ("▣", VIEW_APPS, "Apps", "Apps auxiliares (Ctrl+Shift+6)"),
        ):
            btn = self._make_button(icon, label, view_id, tooltip)
            layout.addWidget(btn)
            self._buttons[view_id] = btn

        layout.addStretch()

        # Action buttons globais — acima do separador de settings, pra
        # liberar espaço na sidebar de workspaces.
        sep_actions = QLabel()
        sep_actions.setFixedHeight(1)
        sep_actions.setStyleSheet(f"background: {theme.BORDER}; margin: 0 10px;")
        layout.addWidget(sep_actions)

        self._open_terminal_btn = _NavButton(
            "›_", "Terminal",
            "Abre um shell embutido em $HOME numa aba nova (sem workspace)",
        )
        self._open_terminal_btn.clicked.connect(self.open_terminal_clicked)
        layout.addWidget(self._open_terminal_btn)

        self._open_claude_btn = _NavButton(
            "✦", "Claude",
            "Abre o Claude embutido numa aba nova, sem workspace (cwd = $HOME)",
        )
        self._open_claude_btn.clicked.connect(self.open_claude_no_ctx_clicked)
        layout.addWidget(self._open_claude_btn)

        self._hack_btn = _NavButton(
            "🔧", "Hack",
            "Abre o Claude no diretório do próprio claude-workspaces pra iterar nele",
        )
        self._hack_btn.clicked.connect(self.hack_app_clicked)
        layout.addWidget(self._hack_btn)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER}; margin: 0 10px;")
        layout.addWidget(sep)

        settings_btn = self._make_button(
            "⚙", "Settings", VIEW_SETTINGS, "Settings"
        )
        layout.addWidget(settings_btn)
        self._buttons[VIEW_SETTINGS] = settings_btn

        # Default ativo: Workspaces
        self._buttons[VIEW_WORKSPACES].setChecked(True)

    def _make_button(
        self, icon: str, label: str, view_id: str, tooltip: str
    ) -> _NavButton:
        btn = _NavButton(icon, label, tooltip)
        btn.clicked.connect(lambda vid=view_id: self._on_clicked(vid))
        return btn

    def _on_clicked(self, view_id: str) -> None:
        # Exclusividade manual — desmarca os outros, marca este, emite
        for vid, b in self._buttons.items():
            b.setChecked(vid == view_id)
        self.view_changed.emit(view_id)

    def set_active(self, view_id: str) -> None:
        """Marca um botão como ativo sem emitir signal (programmatic)."""
        if view_id not in self._buttons:
            return
        for vid, b in self._buttons.items():
            b.setChecked(vid == view_id)

    def activate(self, view_id: str) -> None:
        """Marca um botão como ativo E dispara o view_changed."""
        if view_id in self._buttons:
            self._on_clicked(view_id)

    def set_badge(
        self, view_id: str, text: str, tooltip: str | None = None
    ) -> None:
        """Define o badge (contador) de um botão. text vazio esconde."""
        btn = self._buttons.get(view_id)
        if btn is not None:
            btn.set_badge(text, tooltip)
