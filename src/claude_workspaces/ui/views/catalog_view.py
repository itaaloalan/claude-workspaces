"""Catálogo de skills/agents/commands como view top-level.

Split horizontal: SkillsPanel à esquerda (lista filtrável) + SkillDetailView
à direita (frontmatter, lint, telemetria, body, ações).

Diferente do uso no right_dock (estreito, abre dialog ao clicar), aqui
ocupa janela inteira — o detalhe fica visível ao lado da lista, sem
janela modal.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...models import Workspace
from ..skill_detail_view import SkillDetailView
from ..skills_panel import SkillsPanel

log = logging.getLogger(__name__)


class CatalogView(QWidget):
    def __init__(self, settings=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar com título
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 8, 16, 4)
        title = QLabel("<h2 style='margin:0;'>📚 Catálogo</h2>")
        toolbar.addWidget(title)
        toolbar.addStretch()
        hint = QLabel(
            "<span style='color:#888;'>Single click: detalhe ao lado · "
            "Double click: copiar invocação</span>"
        )
        toolbar.addWidget(hint)
        outer.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )

        # SkillsPanel sem auto-dialog — emite só o signal
        self._list = SkillsPanel(
            settings=settings, auto_open_detail=False,
        )
        list_wrapper = QWidget()
        wl = QVBoxLayout(list_wrapper)
        wl.setContentsMargins(8, 0, 0, 8)
        wl.addWidget(self._list)
        splitter.addWidget(list_wrapper)

        # Detail view
        self._detail = SkillDetailView(settings=settings)
        detail_wrapper = QWidget()
        dl = QVBoxLayout(detail_wrapper)
        dl.setContentsMargins(0, 0, 8, 8)
        dl.addWidget(self._detail)
        splitter.addWidget(detail_wrapper)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 700])
        outer.addWidget(splitter, stretch=1)

        # Wire: seleção na lista → detalhe
        self._list.item_selected.connect(self._on_item_selected)

    def set_workspace(self, workspace: Workspace | None) -> None:
        self._list.set_workspace(workspace)
        ws_folder = (
            workspace.folders[0]
            if workspace and workspace.folders
            else None
        )
        self._detail.set_workspace_folder(ws_folder)
        self._detail.clear()

    def refresh(self) -> None:
        self._list.refresh()

    def _on_item_selected(self, item) -> None:
        catalog_names, ws_folder = self._list.selected_context()
        usage = self._list._usage_for(item)
        self._detail.set_item(
            item, usage, catalog_names, workspace_folder=ws_folder,
        )
