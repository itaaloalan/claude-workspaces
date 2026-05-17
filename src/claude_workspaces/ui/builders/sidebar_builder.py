"""SidebarBuilder — constrói a sidebar de workspaces.

Antes era um método `_build_sidebar` de ~50 linhas no main_window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)


class SidebarBuilder:
    """Constrói a sidebar com lista de workspaces + botões.

    Exporta:
    - `wrapper`: widget pra inserir no splitter
    - `list_widget`: o QTreeWidget (workspaces como roots, sessions/tabs como filhos)
    - `add_btn`: botão "+ Novo Workspace"
    - `self_dev_btn`: botão "🔧 Hack este app"
    """

    def __init__(
        self,
        on_current_changed: Callable,
        on_item_clicked: Callable,
        on_item_activated: Callable,
        on_add_clicked: Callable[[], None],
        on_self_dev_clicked: Callable[[], None],
    ) -> None:
        self._on_current_changed = on_current_changed
        self._on_item_clicked = on_item_clicked
        self._on_item_activated = on_item_activated
        self._on_add_clicked = on_add_clicked
        self._on_self_dev_clicked = on_self_dev_clicked

    def build(self) -> SidebarBuilder:
        self.wrapper = QWidget()
        layout = QVBoxLayout(self.wrapper)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("<b>WORKSPACES</b>"))

        self.list_widget = QTreeWidget()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(True)
        self.list_widget.setIndentation(14)
        self.list_widget.setExpandsOnDoubleClick(False)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemActivated.connect(self._on_item_activated)
        self.list_widget.setStyleSheet(
            "QTreeWidget { background: transparent; border: 0; color: #e6e6e6; }"
            "QTreeWidget::item { padding: 4px 4px; color: #e6e6e6; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
            "QTreeWidget::item:selected:hover { background: #4a82c5; color: #fff; }"
        )
        pal = self.list_widget.palette()
        for grp in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(grp, QPalette.ColorRole.Text, QColor("#e6e6e6"))
            pal.setColor(grp, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            pal.setColor(grp, QPalette.ColorRole.Highlight, QColor("#3d6ea8"))
        self.list_widget.setPalette(pal)
        layout.addWidget(self.list_widget, stretch=1)

        self.add_btn = QPushButton("+ Novo Workspace")
        self.add_btn.setToolTip("Criar novo workspace (Ctrl+N)")
        self.add_btn.clicked.connect(self._on_add_clicked)
        layout.addWidget(self.add_btn)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a;")
        layout.addWidget(sep)

        self.self_dev_btn = QPushButton("🔧 Hack este app")
        self.self_dev_btn.setToolTip(
            "Abre o Claude no diretório do próprio claude-workspaces pra iterar nele"
        )
        self.self_dev_btn.clicked.connect(self._on_self_dev_clicked)
        layout.addWidget(self.self_dev_btn)

        return self
