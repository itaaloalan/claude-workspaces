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


class _StableTree(QTreeWidget):
    """QTreeWidget que ignora drag de seleção. No comportamento padrão,
    com botão esquerdo pressionado, o `currentItem` segue o cursor — qualquer
    micro-arrasto entre rows muda a seleção. Mouse com chatter no switch
    do botão esquerdo dispara press+move+release sobre múltiplos itens num
    "clique único", fazendo a seleção pular pro último item sob o ponteiro
    (sintoma reportado: clicar num console e cair em outro workspace).

    Defesa: na MoveEvent com botão esquerdo segurado, NÃO propagamos o
    evento — assim a seleção fica travada no item do press. No release,
    se o ponteiro saiu do item original, restauramos a seleção pro
    item onde o press começou.
    """

    # Debounce: presses esquerda mais próximos do que esse intervalo são
    # considerados chatter do switch e ignorados (não chegam ao base).
    _PRESS_DEBOUNCE_MS = 120

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            from PySide6.QtCore import QDateTime
            now = QDateTime.currentMSecsSinceEpoch()
            last = getattr(self, "_last_press_ms", 0)
            if now - last < self._PRESS_DEBOUNCE_MS:
                # Press espúrio (chatter) — ignora completamente.
                event.accept()
                return
            self._last_press_ms = now
            self._press_item = self.itemAt(event.position().toPoint())
        else:
            self._press_item = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        # Ignora QUALQUER move — com ou sem botão. Sem isso, mouse com
        # chatter consegue mudar a seleção mesmo sem segurar o clique
        # (o switch dispara press espúrios durante o movimento, então
        # mover o cursor pra baixo "arrasta" a seleção pro item abaixo).
        return

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            press_item = getattr(self, "_press_item", None)
            release_item = self.itemAt(event.position().toPoint())
            if press_item is not None and release_item is not press_item:
                self.setCurrentItem(press_item)
                return
        super().mouseReleaseEvent(event)


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
    # Layout limpo: sem bordas no item, só mudança discreta de bg na
    # seleção/hover. O respiro entre cards vem do `setSpacing` do tree
    # (via showGridLines/padding interno do widget) e do padding-bottom
    # do header de workspace. Removido o border-bottom separador (poluía
    # visualmente quando combinado com a borda da seleção).
    f"QTreeWidget::item {{"
    f"  padding: 1px 2px;"
    f"  border: 0;"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    # Sem background em hover/seleção — o `_status_strip` colorido no
    # canto esquerdo do card já é pista visual suficiente. Qualquer tint
    # no row fazia o card parecer "ativado/destacado" e poluía o painel.
    f"QTreeWidget::item:hover {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_BRIGHT};"
    f"}}"
    f"QTreeWidget::item:selected {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
    f"QTreeWidget::item:selected:hover {{"
    f"  background: transparent;"
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
    - `version_label`: label clicável com a versão atual (abre release notes)
    """

    def __init__(
        self,
        on_current_changed: Callable,
        on_item_clicked: Callable,
        on_item_activated: Callable,
        on_add_clicked: Callable[[], None],
        on_version_clicked: Callable[[], None] | None = None,
        on_find_file: Callable[[str], None] | None = None,
        on_search_workspaces: Callable[[str], None] | None = None,
    ) -> None:
        self._on_current_changed = on_current_changed
        self._on_item_clicked = on_item_clicked
        self._on_item_activated = on_item_activated
        self._on_add_clicked = on_add_clicked
        self._on_version_clicked = on_version_clicked
        self._on_find_file = on_find_file
        self._on_search_workspaces = on_search_workspaces

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

        # Botão + (novo workspace) e filtro funnel na row do header
        # WORKSPACES — espelha o mockup, dá ações 1-clique sem precisar
        # do botão grande no rodapé.
        from PySide6.QtCore import QSize
        from ..icons import ICONS, ic as _ic
        self.header_add_btn = QPushButton()
        self.header_add_btn.setIcon(_ic(ICONS["add"], color="#9aa0a6"))
        self.header_add_btn.setIconSize(QSize(11, 11))
        self.header_add_btn.setFixedSize(20, 18)
        self.header_add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header_add_btn.setToolTip("Criar novo workspace (Ctrl+N)")
        self.header_add_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; padding: 0; }"
            "QPushButton:hover { background: #2a2a2a; border-radius: 3px; }"
        )
        self.header_add_btn.clicked.connect(self._on_add_clicked)
        header_layout.addWidget(self.header_add_btn, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(header_row)

        # Input local de busca workspaces (espelha o filtro do top bar
        # mas fica colado na lista, igual VSCode/JetBrains).
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar workspaces…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 5px 8px; color: #e6e6e6; font-size: 11px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
            "QLineEdit { selection-background-color: #3d6ea8; }"
        )
        # Placeholder mais visível (default fica quase invisível em tema escuro)
        pal = self.search_input.palette()
        from PySide6.QtGui import QColor
        pal.setColor(pal.ColorRole.PlaceholderText, QColor("#888"))
        self.search_input.setPalette(pal)
        if self._on_search_workspaces is not None:
            self.search_input.textChanged.connect(self._on_search_workspaces)

        # Wrappa o input num row com filtro funnel à direita (mockup).
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        search_row.addWidget(self.search_input, stretch=1)
        self.filter_btn = QPushButton()
        self.filter_btn.setIcon(_ic(ICONS["filter"], color="#9aa0a6"))
        self.filter_btn.setIconSize(QSize(12, 12))
        self.filter_btn.setFixedSize(28, 26)
        self.filter_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.filter_btn.setToolTip("Filtros avançados (em breve)")
        self.filter_btn.setStyleSheet(
            "QPushButton { background: #1f1f1f; border: 1px solid #2c2c2c; border-radius: 4px; }"
            "QPushButton:hover { border-color: #3d6ea8; }"
        )
        search_row.addWidget(self.filter_btn)
        layout.addLayout(search_row)

        self.list_widget = _StableTree()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(True)
        self.list_widget.setIndentation(6)
        self.list_widget.setUniformRowHeights(False)
        self.list_widget.setAnimated(True)
        self.list_widget.setExpandsOnDoubleClick(False)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemActivated.connect(self._on_item_activated)
        self.list_widget.setStyleSheet(_TREE_QSS)
        self.list_widget.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
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
        ctx_outer = QVBoxLayout(self.context_status_container)
        ctx_outer.setContentsMargins(0, 0, 0, 0)
        ctx_outer.setSpacing(0)

        ctx_row_widget = QWidget()
        ctx_row = QHBoxLayout(ctx_row_widget)
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
        ctx_outer.addWidget(ctx_row_widget)

        # Linha secundária: "atualizado há Xmin" — pequeno e discreto,
        # só pra dar noção de quão recente está o snapshot exibido.
        self.context_status_updated_label = QLabel("")
        self.context_status_updated_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_DISABLED}; "
            "font-size: 9px; padding: 0px 4px 4px 4px; }}"
        )
        self.context_status_updated_label.setVisible(False)
        ctx_outer.addWidget(self.context_status_updated_label)

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
        self.add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.add_btn.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_btn)

        # Os botões "Abrir Terminal", "Claude (sem contexto)" e
        # "Hack este app" vivem na activity bar à esquerda — libera
        # espaço vertical aqui pra lista de workspaces.

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
