"""SidebarBuilder — constrói a sidebar de workspaces.

Antes era um método `_build_sidebar` de ~50 linhas no main_window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

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

    # --- Overlay de bordas pra fechar workspaces expandidos visualmente.
    # WorkspaceItemWidget achata bordas inferiores no estado expandido;
    # essa pintura conecta as laterais e fecha o bottom englobando todos
    # os descendentes visíveis (Sessões Claude, Runners, etc).

    def setup_card_overlay(self) -> None:
        """Overlay de bordas removido — a lista fica flat sem caixas."""
        pass

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        ov = getattr(self, "_card_overlay", None)
        if ov is not None:
            ov.setGeometry(self.viewport().rect())

    def _last_visible_descendant(
        self, item: QTreeWidgetItem
    ) -> QTreeWidgetItem | None:
        """Walk down expanded children pra achar o último item visível
        (recursivo). Itens hidden são pulados — eles não ocupam rect."""
        last = item
        cur = item
        while cur.isExpanded() and cur.childCount() > 0:
            found = None
            for i in range(cur.childCount() - 1, -1, -1):
                ch = cur.child(i)
                if not ch.isHidden():
                    found = ch
                    break
            if found is None:
                break
            last = found
            cur = found
        return last if last is not item else (item if item.isExpanded() else None)


class _WorkspaceBorderOverlay(QWidget):
    """Pinta laterais + base do "card contínuo" de cada workspace
    expandido. Fica em cima da viewport mas é transparente pra mouse,
    então não atrapalha cliques/scroll. Cor da borda acompanha o
    estado de seleção do workspace — azul (PRIMARY) quando selecionado,
    cinza neutro caso contrário."""

    _BORDER_COLOR = QColor("#333333")
    _BORDER_COLOR_SELECTED = QColor(theme.PRIMARY)
    _BORDER_RADIUS = 6

    def __init__(self, tree: _StableTree) -> None:
        super().__init__(tree.viewport())
        self._tree = tree
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # `_TREE_QSS` aplica `QTreeWidget::item { padding: 1px 2px; }` —
    # então o widget (e sua borda) fica inset 2px nas laterais e 1px
    # vertical em relação ao rect do item. Compensar pra borda do
    # overlay alinhar com a borda do card e dos children.
    _PAD_X = 2
    _PAD_Y = 1

    def _workspace_selected(self, top: QTreeWidgetItem) -> bool:
        """Verifica se o workspace está no estado 'selected' lendo direto
        do WorkspaceItemWidget — assim a borda do overlay acompanha a
        mesma regra de seleção que já é aplicada no header (que segue
        seleção do workspace OU de qualquer descendant)."""
        from ..workspace_item_widget import WorkspaceItemWidget
        w = self._tree.itemWidget(top, 0)
        if isinstance(w, WorkspaceItemWidget):
            return getattr(w, "_selected", False)
        return False

    def paintEvent(self, event) -> None:  # type: ignore[override]
        tree = self._tree
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        vp_bottom = tree.viewport().height()
        count = tree.topLevelItemCount()
        for i in range(count):
            top = tree.topLevelItem(i)
            if not top.isExpanded():
                continue
            top_rect = tree.visualItemRect(top)
            if not top_rect.isValid() or top_rect.height() == 0:
                continue
            if tree._last_visible_descendant(top) is None:
                # Workspace expandido mas sem nenhum descendente visível —
                # não há "card contínuo" pra fechar.
                continue
            selected = self._workspace_selected(top)
            pen = QPen(
                self._BORDER_COLOR_SELECTED if selected else self._BORDER_COLOR
            )
            pen.setWidth(1)
            painter.setPen(pen)
            # Compensa padding do item — borda do widget está inset.
            x_left = top_rect.left() + self._PAD_X
            x_right = top_rect.right() - self._PAD_X
            # Começa LOGO antes do bottom do widget do header pra cobrir
            # a junção e não deixar gap visível.
            y_top = top_rect.bottom() - self._PAD_Y
            # A base do frame é o LIMITE do workspace, não o
            # `visualItemRect` do último descendente: com o scroll no fim
            # esse rect às vezes vem curto demais (fecha o frame cedo e
            # deixa a sessão de fora) ou comprido demais (invade o próximo).
            # Como os filhos são contíguos, o topo do PRÓXIMO item top-level
            # (workspace OU divisória "WORKSPACES") é a fronteira real.
            next_top: int | None = None
            for j in range(i + 1, count):
                nxt_rect = tree.visualItemRect(tree.topLevelItem(j))
                if nxt_rect.isValid() and nxt_rect.height() > 0:
                    next_top = nxt_rect.top()
                    break
            if next_top is not None:
                y_bottom = next_top - self._PAD_Y
            else:
                # Último item visível (sem próximo top-level): usa a base do
                # último descendente, ou o fundo do viewport se ele estiver
                # rolado pra fora (rect inválido).
                last = tree._last_visible_descendant(top)
                last_rect = tree.visualItemRect(last) if last is not None else QRect()
                y_bottom = (
                    last_rect.bottom() - self._PAD_Y
                    if last_rect.isValid()
                    else vp_bottom
                )
            # Nunca passa do fundo do viewport.
            y_bottom = min(y_bottom, vp_bottom)
            if y_bottom <= y_top:
                continue
            r = self._BORDER_RADIUS
            # Laterais verticais (até onde começa o arco do canto inferior).
            painter.drawLine(x_left, y_top, x_left, y_bottom - r)
            painter.drawLine(x_right, y_top, x_right, y_bottom - r)
            # Base com cantos arredondados — desenhamos a curva inferior +
            # a linha horizontal central como um path.
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(x_left, y_bottom - r)
            path.quadTo(x_left, y_bottom, x_left + r, y_bottom)
            path.lineTo(x_right - r, y_bottom)
            path.quadTo(x_right, y_bottom, x_right, y_bottom - r)
            painter.drawPath(path)
        painter.end()


_SECTION_HEADER_QSS = (
    "QLabel {"
    "  color: #7d838b;"
    "  font-size: 10px;"
    "  font-weight: 700;"
    "  letter-spacing: 1.4px;"
    "  padding: 2px 4px 4px 4px;"
    "}"
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
    f"  padding: 1px 4px;"
    f"  border: 0;"
    f"  border-radius: 6px;"
    f"  color: {theme.TEXT_PRIMARY};"
    f"}}"
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
    # Branch indicators do Qt ocultos — hierarquia fica implícita na
    # indentação e nos custom widgets (WorkspaceItemWidget / TerminalChildWidget).
    f"QTreeWidget::branch {{"
    f"  background: transparent;"
    f"  image: none;"
    f"  border: 0;"
    f"  width: 0px;"
    f"}}"
)

_HEADER_ICON_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  border: 0;"
    f"  border-radius: {theme.RADIUS_SM}px;"
    f"  color: {theme.TEXT_FAINT};"
    f"  font-size: 13px;"
    f"  padding: 0;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
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
        from PySide6.QtCore import QSize

        from ..icons import ICONS
        from ..icons import ic as _ic

        self.wrapper = QWidget()
        self.wrapper.setStyleSheet("background: #171717;")
        layout = QVBoxLayout(self.wrapper)
        layout.setContentsMargins(10, 10, 8, 6)
        layout.setSpacing(7)

        # Search row primeiro — search alinhado no topo igual ao mockup.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar workspaces…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(theme.line_edit_qss())
        pal = self.search_input.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(theme.TEXT_FAINT))
        self.search_input.setPalette(pal)
        self.search_input.setFixedHeight(28)
        if self._on_search_workspaces is not None:
            self.search_input.textChanged.connect(self._on_search_workspaces)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        search_row.addWidget(self.search_input, stretch=1)
        self.filter_btn = QPushButton()
        self.filter_btn.setIcon(_ic(ICONS["filter"], color=theme.TEXT_FAINT))
        self.filter_btn.setIconSize(QSize(12, 12))
        self.filter_btn.setFixedSize(28, 28)
        self.filter_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.filter_btn.setToolTip("Filtros avançados (em breve)")
        self.filter_btn.setStyleSheet(
            "QPushButton { background: #1b1b1b; "
            "border: 1px solid #292929; border-radius: 6px; }"
            f"QPushButton:hover {{ border-color: {theme.PRIMARY}; background: #202020; }}"
        )
        search_row.addWidget(self.filter_btn)
        layout.addLayout(search_row)

        # Seções ATENÇÃO e FIXADOS — começam ocultas; MainWindow popula
        # via set_attention_items/set_pinned_items (stubs por enquanto).
        self.attention_section = self._make_section_container("ATENÇÃO")
        self.attention_section.setVisible(False)
        layout.addWidget(self.attention_section)

        self.pinned_section = self._make_section_container("FIXADOS")
        self.pinned_section.setVisible(False)
        layout.addWidget(self.pinned_section)

        # Header WORKSPACES — label + count chip + botões à direita.
        header_row = QWidget()
        header_row.setObjectName("WorkspacesHeaderRow")
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 12, 0, 0)
        header_layout.setSpacing(6)
        header = QLabel("WORKSPACES")
        header.setStyleSheet(theme.section_header_qss())
        header_layout.addWidget(header, 0)

        self.workspaces_count_label = QLabel("")
        self.workspaces_count_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; background: rgba(255,255,255,16); "
            f"font-size: 9px; font-weight: 700; padding: 1px 6px; "
            f"border-radius: 7px; }}"
        )
        self.workspaces_count_label.setVisible(False)
        header_layout.addWidget(self.workspaces_count_label, 0, Qt.AlignmentFlag.AlignVCenter)

        header_layout.addStretch(1)

        # actions_toggle_btn é mantido (MainWindow conecta nele), mas
        # agora vive escondido — comportamento exposto via menu ⋯.
        self.actions_toggle_btn = QPushButton("⌃")
        self.actions_toggle_btn.setStyleSheet(_HEADER_TOGGLE_QSS)
        self.actions_toggle_btn.setVisible(False)

        self.header_add_btn = QPushButton()
        self.header_add_btn.setIcon(_ic(ICONS["add"], color=theme.TEXT_FAINT))
        self.header_add_btn.setIconSize(QSize(12, 12))
        self.header_add_btn.setFixedSize(22, 20)
        self.header_add_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header_add_btn.setToolTip("Criar novo workspace (Ctrl+N)")
        self.header_add_btn.setStyleSheet(_HEADER_ICON_BTN_QSS)
        self.header_add_btn.clicked.connect(self._on_add_clicked)
        header_layout.addWidget(self.header_add_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.header_more_btn = QPushButton("⋯")
        self.header_more_btn.setFixedSize(22, 20)
        self.header_more_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.header_more_btn.setStyleSheet(_HEADER_ICON_BTN_QSS)
        self.header_more_btn.setToolTip(
            "Mais ações (mostrar/ocultar atalhos nos consoles, etc.)"
        )
        self.header_more_btn.clicked.connect(self._open_header_menu)
        header_layout.addWidget(self.header_more_btn, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(header_row)

        self.list_widget = _StableTree()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(True)
        # Indentação leve: deixa claro que consoles/runners pertencem ao
        # workspace sem criar uma árvore visual pesada.
        self.list_widget.setIndentation(0)
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
        # Overlay que pinta laterais + base dos workspaces expandidos,
        # fechando visualmente o "card contínuo".
        self.list_widget.setup_card_overlay()

        # find_file_input — mantido como stub oculto (main_window acessa)
        self.find_file_input = QLineEdit()
        self.find_file_input.setVisible(False)
        if self._on_find_file is not None:
            self.find_file_input.returnPressed.connect(
                lambda: self._on_find_file(self.find_file_input.text())
            )

        # Footer compacto: version, chip de uso, chip de minimizados.
        # Expõe os mesmos atributos que o main_window espera.
        from ..sidebar_footer import SidebarFooter
        self._footer = SidebarFooter(on_version_clicked=self._on_version_clicked)
        layout.addWidget(self._footer)

        # Reassign pra manter compatibilidade com main_window.py sem mudanças.
        self.context_status_label = self._footer.context_status_label
        self.context_status_container = self._footer.usage_detail_panel
        self.context_status_refresh_btn = self._footer.context_status_refresh_btn
        self.context_status_updated_label = self._footer.context_status_updated_label
        self.console_runner_requested = self._footer.console_runner_requested
        self.runner_toggle_requested = self._footer.runner_toggle_requested
        self.set_console_runners = self._footer.set_console_runners
        self.version_label = self._footer.version_label
        self.minimized_tray = self._footer.minimized_tray
        self.add_btn = self.header_add_btn  # alias — header já tem o botão +

        return self

    # ---------- helpers de seção / API pública ----------

    def _make_section_container(self, title: str) -> QFrame:
        """Container colapsável com header (sm-caps + count chip) + body
        que recebe filhos via .body_layout. Começa oculto; o caller chama
        setVisible(True) quando popular."""
        container = QFrame()
        container.setObjectName(f"Section_{title}")
        container.setStyleSheet("QFrame { background: transparent; border: 0; }")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(theme.section_header_qss())
        head_row.addWidget(title_label, 0)

        count_label = QLabel("")
        count_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; background: {theme.BG_SURFACE}; "
            f"font-size: 9px; font-weight: 700; padding: 1px 6px; "
            f"border-radius: 7px; }}"
        )
        count_label.setVisible(False)
        head_row.addWidget(count_label, 0, Qt.AlignmentFlag.AlignVCenter)
        head_row.addStretch(1)
        vbox.addLayout(head_row)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        vbox.addWidget(body)

        # Expostos no próprio container pra MainWindow popular.
        container.count_label = count_label  # type: ignore[attr-defined]
        container.body_layout = body_layout  # type: ignore[attr-defined]
        return container

    def _open_header_menu(self) -> None:
        """Menu ⋯ do header WORKSPACES — agrupa ações secundárias que
        antes poluíam a row do header (toggle de atalhos inline, etc).
        Dispara o mesmo signal de `actions_toggle_btn` pra MainWindow."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self.header_more_btn)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.BG_SURFACE}; "
            f"color: {theme.TEXT_PRIMARY}; border: 1px solid {theme.BORDER_INPUT}; }}"
            f"QMenu::item {{ padding: 6px 14px; }}"
            f"QMenu::item:selected {{ background: {theme.PRIMARY}; color: {theme.TEXT_BRIGHT}; }}"
        )
        toggle_action = menu.addAction(self.actions_toggle_btn.toolTip().split(".")[0])
        toggle_action.triggered.connect(self.actions_toggle_btn.click)
        menu.addAction("Criar novo workspace…").triggered.connect(self._on_add_clicked)
        menu.exec_(self.header_more_btn.mapToGlobal(
            self.header_more_btn.rect().bottomRight()
        ))

    def set_workspaces_count(self, n: int) -> None:
        """Atualiza o chip de contagem ao lado de WORKSPACES."""
        if n <= 0:
            self.workspaces_count_label.setVisible(False)
            return
        self.workspaces_count_label.setText(str(n))
        self.workspaces_count_label.setVisible(True)

    def set_attention_items(self, items: list[QWidget]) -> None:
        """Popula a seção ATENÇÃO com cards já-prontos. Esconde se vazio."""
        body = self.attention_section.body_layout  # type: ignore[attr-defined]
        while body.count():
            it = body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for w in items:
            body.addWidget(w)
        self.attention_section.count_label.setText(str(len(items)))  # type: ignore[attr-defined]
        self.attention_section.count_label.setVisible(bool(items))  # type: ignore[attr-defined]
        self.attention_section.setVisible(bool(items))

    def set_pinned_items(self, items: list[QWidget]) -> None:
        """Popula FIXADOS com cards já-prontos. Esconde se vazio."""
        body = self.pinned_section.body_layout  # type: ignore[attr-defined]
        while body.count():
            it = body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for w in items:
            body.addWidget(w)
        self.pinned_section.count_label.setText(str(len(items)))  # type: ignore[attr-defined]
        self.pinned_section.count_label.setVisible(bool(items))  # type: ignore[attr-defined]
        self.pinned_section.setVisible(bool(items))
