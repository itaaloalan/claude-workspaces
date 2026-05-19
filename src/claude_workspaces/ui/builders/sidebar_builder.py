"""SidebarBuilder — constrói a sidebar de workspaces.

Antes era um método `_build_sidebar` de ~50 linhas no main_window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from .. import theme


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


_SECTION_HEADER_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_FAINT};"
    f"  font-size: 10px;"
    f"  font-weight: 700;"
    f"  letter-spacing: 1.4px;"
    f"  padding: 2px 4px 6px 4px;"
    f"}}"
)

_SECTION_HEADER_ROW_QSS = (
    f"QWidget#WorkspacesHeaderRow {{"
    f"  border-bottom: 1px solid {theme.BORDER_SOFT};"
    f"}}"
)

_HEADER_TOGGLE_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: 4px;"
    f"  padding: 0px 6px;"
    f"  font-size: 11px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)

_TREE_QSS = (
    f"QTreeWidget {{"
    f"  background: transparent;"
    f"  border: 0;"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  outline: 0;"
    f"}}"
    f"QTreeWidget::item {{"
    f"  padding: 5px 6px;"
    f"  border-left: 2px solid transparent;"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    f"QTreeWidget::item:hover {{"
    f"  background: transparent;"
    f"  border-left: 2px solid {theme.BORDER_INPUT};"
    f"  color: {theme.TEXT_BRIGHT};"
    f"}}"
    f"QTreeWidget::item:selected {{"
    f"  background: transparent;"
    f"  border-left: 2px solid {theme.TEXT_LINK};"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    f"QTreeWidget::item:selected:hover {{"
    f"  background: transparent;"
    f"  border-left: 2px solid {theme.PRIMARY_HOVER};"
    f"  color: {theme.TEXT_BRIGHT};"
    f"}}"
    f"QTreeWidget::branch {{ background: transparent; }}"
)

_PRIMARY_ACTION_QSS = (
    f"QPushButton {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  border: 1px solid {theme.BORDER_INPUT};"
    f"  border-radius: 6px;"
    f"  padding: 6px 12px;"
    f"  text-align: left;"
    f"}}"
    f"QPushButton:hover {{"
    f"  border-color: {theme.PRIMARY};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
    f"QPushButton:pressed {{"
    f"  background: {theme.BG_PANEL};"
    f"}}"
)

_GHOST_ACTION_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: 4px;"
    f"  padding: 5px 10px;"
    f"  text-align: left;"
    f"  font-size: 11px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
)

_VERSION_LABEL_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_FAINT};"
    f"  font-size: 10px;"
    f"  padding: 4px 10px 2px 10px;"
    f"}}"
    f"QLabel:hover {{"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)

_CONTEXT_STATUS_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_FADED};"
    f"  font-size: 11px;"
    f"  padding: 2px 4px 4px 4px;"
    f"}}"
)


class SidebarBuilder:
    """Constrói a sidebar com lista de workspaces + botões.

    Exporta:
    - `wrapper`: widget pra inserir no splitter
    - `list_widget`: o QTreeWidget (workspaces como roots, sessions/tabs como filhos)
    - `context_status_label`: label do % de contexto da sessão ativa (oculto se sem sessão)
    - `add_btn`: botão "+ Novo Workspace"
    - `self_dev_btn`: botão "🔧 Hack este app"
    - `version_label`: label clicável com a versão atual (abre release notes)
    """

    def __init__(
        self,
        on_current_changed: Callable,
        on_item_clicked: Callable,
        on_item_activated: Callable,
        on_add_clicked: Callable[[], None],
        on_self_dev_clicked: Callable[[], None],
        on_version_clicked: Callable[[], None] | None = None,
        on_find_file: Callable[[str], None] | None = None,
    ) -> None:
        self._on_current_changed = on_current_changed
        self._on_item_clicked = on_item_clicked
        self._on_item_activated = on_item_activated
        self._on_add_clicked = on_add_clicked
        self._on_self_dev_clicked = on_self_dev_clicked
        self._on_version_clicked = on_version_clicked
        self._on_find_file = on_find_file

    def build(self) -> SidebarBuilder:
        self.wrapper = QWidget()
        self.wrapper.setStyleSheet(f"background: {theme.BG_PANEL};")
        layout = QVBoxLayout(self.wrapper)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        # Header "WORKSPACES" + toggle das ações inline nos consoles
        # (▶ Continuar / ⚙ Modo). Texto/tooltip do botão é refrescado
        # pela MainWindow via `set_child_actions_visible`.
        header_row = QWidget()
        header_row.setObjectName("WorkspacesHeaderRow")
        header_row.setStyleSheet(_SECTION_HEADER_ROW_QSS)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header = QLabel("WORKSPACES")
        header.setStyleSheet(_SECTION_HEADER_QSS)
        header_layout.addWidget(header, stretch=1)
        self.actions_toggle_btn = QPushButton("⌃")
        self.actions_toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.actions_toggle_btn.setStyleSheet(_HEADER_TOGGLE_QSS)
        self.actions_toggle_btn.setFixedHeight(18)
        self.actions_toggle_btn.setToolTip(
            "Ocultar/mostrar os botões ▶ Continuar / ⚙ Modo em cada"
            " console. As ações continuam acessíveis no menu de contexto."
        )
        header_layout.addWidget(self.actions_toggle_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(header_row)

        self.list_widget = QTreeWidget()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(True)
        self.list_widget.setIndentation(12)
        self.list_widget.setUniformRowHeights(False)
        self.list_widget.setAnimated(True)
        self.list_widget.setExpandsOnDoubleClick(False)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemActivated.connect(self._on_item_activated)
        self.list_widget.setStyleSheet(_TREE_QSS)
        pal = self.list_widget.palette()
        for grp in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(grp, QPalette.ColorRole.Text, QColor(theme.TEXT_PRIMARY))
            # HighlightedText = Text: seleção não muda a cor do texto (evita
            # aparência de "trecho copiado"). O destaque vem da borda lateral
            # + fundo neutro definidos no QSS.
            pal.setColor(grp, QPalette.ColorRole.HighlightedText, QColor(theme.TEXT_PRIMARY))
            pal.setColor(grp, QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        self.list_widget.setPalette(pal)
        layout.addWidget(self.list_widget, stretch=1)

        # Status do contexto da sessão Claude ativa (apenas % da janela
        # de contexto + tokens absolutos). Atualizado pela MainWindow no
        # mesmo poll que atualiza git/tokens (5s). Fica oculto enquanto
        # não há sessão ativa pra evitar ruído visual.
        # Linha 1: label do uso. Linha 2 (dentro da mesma row): botão
        # refresh + timestamp do último sync. Tudo agrupado num container
        # pra esconder/mostrar junto.
        self.context_status_container = QWidget()
        ctx_row = QHBoxLayout(self.context_status_container)
        ctx_row.setContentsMargins(0, 0, 0, 0)
        ctx_row.setSpacing(6)

        self.context_status_label = QLabel("")
        self.context_status_label.setStyleSheet(_CONTEXT_STATUS_QSS)
        self.context_status_label.setTextFormat(Qt.TextFormat.RichText)
        ctx_row.addWidget(self.context_status_label, stretch=1)

        # Botão refresh — clicável, força chamada nova do
        # /api/oauth/usage (ignora cache + cooldown). Discreto: só o
        # ícone unicode "⟳", do mesmo tom faint do texto.
        self.context_status_refresh_btn = QPushButton("⟳")
        self.context_status_refresh_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        self.context_status_refresh_btn.setToolTip(
            "Forçar sincronização do uso do plano com /api/oauth/usage"
        )
        self.context_status_refresh_btn.setFlat(True)
        self.context_status_refresh_btn.setFixedSize(20, 20)
        self.context_status_refresh_btn.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_FAINT}; "
            "background: transparent; border: none; font-size: 13px; "
            "padding: 0px; }"
            f"QPushButton:hover {{ color: {theme.TEXT_PRIMARY}; }}"
            "QPushButton:disabled { color: #555; }"
        )
        ctx_row.addWidget(
            self.context_status_refresh_btn,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        self.context_status_container.setVisible(False)
        layout.addWidget(self.context_status_container)

        # Localizar arquivo — input compacto que abre um modal de busca
        # com os resultados do workspace ativo. Mora aqui na sidebar
        # (esquerda) pra ficar acessível independente da view atual.
        self.find_file_input = QLineEdit()
        self.find_file_input.setPlaceholderText("🔍  Localizar arquivo…")
        self.find_file_input.setClearButtonEnabled(True)
        self.find_file_input.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 5px 8px; color: #e6e6e6; font-size: 11px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        if self._on_find_file is not None:
            self.find_file_input.returnPressed.connect(
                lambda: self._on_find_file(self.find_file_input.text())
            )
        layout.addWidget(self.find_file_input)

        self.add_btn = QPushButton("＋  Novo Workspace")
        self.add_btn.setToolTip("Criar novo workspace (Ctrl+N)")
        self.add_btn.setStyleSheet(_PRIMARY_ACTION_QSS)
        self.add_btn.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_btn)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER_SOFT};")
        layout.addWidget(sep)

        self.self_dev_btn = QPushButton("🔧  Hack este app")
        self.self_dev_btn.setToolTip(
            "Abre o Claude no diretório do próprio claude-workspaces pra iterar nele"
        )
        self.self_dev_btn.setStyleSheet(_GHOST_ACTION_QSS)
        self.self_dev_btn.clicked.connect(self._on_self_dev_clicked)
        layout.addWidget(self.self_dev_btn)

        self.version_label = _ClickableLabel(f"v{__version__}  ·  notas")
        self.version_label.setStyleSheet(_VERSION_LABEL_QSS)
        self.version_label.setToolTip(
            "Ver o que mudou nesta versão e o histórico completo"
        )
        self.version_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self._on_version_clicked is not None:
            self.version_label.clicked.connect(self._on_version_clicked)
        layout.addWidget(self.version_label)

        return self
