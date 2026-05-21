"""FilesPanel — árvore de arquivos do workspace ativo no right dock.

Usa QFileSystemModel apontando pra primeira pasta do workspace. Click
duplo num arquivo abre no editor configurado (VSCode/IDE) via signal.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace
from .icons import ICONS, ic


class FilesPanel(QWidget):
    """Árvore de arquivos do workspace ativo. Click duplo emite signal
    `open_file_requested(str)` com o path absoluto."""

    open_file_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workspace: Workspace | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header com botão de refresh e label do path raiz
        header = QWidget()
        header.setStyleSheet(
            "background: #161616; border-bottom: 1px solid #2a2a2a;"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)
        self._root_label = QLabel("(nenhum workspace)")
        self._root_label.setStyleSheet(
            "color: #9aa0a6; font-size: 11px;"
        )
        h.addWidget(self._root_label, stretch=1)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setIcon(ic("fa5s.sync-alt", color="#9aa0a6"))
        self._refresh_btn.setIconSize(QSize(11, 11))
        self._refresh_btn.setFixedSize(22, 22)
        self._refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_btn.setToolTip("Recarregar árvore de arquivos")
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; }"
            "QPushButton:hover { background: #2a2a2a; border-radius: 3px; }"
        )
        self._refresh_btn.clicked.connect(self._reload)
        h.addWidget(self._refresh_btn)

        layout.addWidget(header)

        # Árvore de arquivos
        self._model = QFileSystemModel()
        self._model.setFilter(
            QDir.Filter.AllDirs
            | QDir.Filter.Files
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Hidden
        )

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setStyleSheet(
            "QTreeView { background: #181818; color: #e6e6e6; border: 0; outline: 0; }"
            "QTreeView::item { padding: 2px 4px; }"
            "QTreeView::item:hover { background: #1f1f1f; }"
            "QTreeView::item:selected { background: #2a2a2a; color: #fff; }"
            "QTreeView::branch { background: transparent; }"
        )
        self._tree.doubleClicked.connect(self._on_double_click)
        # Esconde colunas extras (size, type, date) — só o nome.
        for col in (1, 2, 3):
            self._tree.setColumnHidden(col, True)
        # Coluna 0 expande pra largura total
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._tree, stretch=1)

    def set_workspace(self, workspace: Workspace | None) -> None:
        """Aponta a árvore pra primeira pasta do workspace."""
        self._workspace = workspace
        if workspace is None or not workspace.folders:
            self._root_label.setText("(nenhum workspace selecionado)")
            self._model.setRootPath("")
            return
        root = workspace.folders[0]
        self._root_label.setText(Path(root).name)
        self._root_label.setToolTip(root)
        idx = self._model.setRootPath(root)
        self._tree.setRootIndex(idx)

    def _reload(self) -> None:
        # Re-aponta pra mesma pasta — força refresh do filesystem
        self.set_workspace(self._workspace)

    def _on_double_click(self, index: QModelIndex) -> None:
        path = self._model.filePath(index)
        if path and not self._model.isDir(index):
            self.open_file_requested.emit(path)
