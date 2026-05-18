"""SidebarBuilder — constrói a sidebar de workspaces.

Antes era um método `_build_sidebar` de ~50 linhas no main_window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QLabel,
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
    f"  border-bottom: 1px solid {theme.BORDER_SOFT};"
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
    f"  color: {theme.TEXT_BRIGHT};"
    f"}}"
    f"QTreeWidget::item:selected {{"
    f"  background: transparent;"
    f"  border-left: 2px solid {theme.TEXT_LINK};"
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


class SidebarBuilder:
    """Constrói a sidebar com lista de workspaces + botões.

    Exporta:
    - `wrapper`: widget pra inserir no splitter
    - `list_widget`: o QTreeWidget (workspaces como roots, sessions/tabs como filhos)
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
    ) -> None:
        self._on_current_changed = on_current_changed
        self._on_item_clicked = on_item_clicked
        self._on_item_activated = on_item_activated
        self._on_add_clicked = on_add_clicked
        self._on_self_dev_clicked = on_self_dev_clicked
        self._on_version_clicked = on_version_clicked

    def build(self) -> SidebarBuilder:
        self.wrapper = QWidget()
        self.wrapper.setStyleSheet(f"background: {theme.BG_PANEL};")
        layout = QVBoxLayout(self.wrapper)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        header = QLabel("WORKSPACES")
        header.setStyleSheet(_SECTION_HEADER_QSS)
        layout.addWidget(header)

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
