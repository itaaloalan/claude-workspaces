"""FilesPanel — árvore de arquivos do workspace ativo no right dock.

Usa QFileSystemModel apontando pra primeira pasta do workspace. Click
duplo num arquivo abre no editor configurado (VSCode/IDE) via signal.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDir,
    QModelIndex,
    QSize,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace
from .icons import ic


class FilesPanel(QWidget):
    """Árvore de arquivos do workspace ativo. Click duplo emite signal
    `open_file_requested(str)` com o path absoluto."""

    open_file_requested = Signal(str)

    def __init__(self, settings=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workspace: Workspace | None = None
        self._settings = settings

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

        # Search input — filtra itens visíveis por nome. Limita ao que já
        # foi carregado pelo QFileSystemModel (que é lazy); pra busca
        # recursiva profunda, usar o file_finder dialog (Ctrl+P).
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Localizar em arquivos…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 4px 8px; color: #e6e6e6; "
            "font-size: 11px; margin: 4px 6px 4px 6px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_input)

        # Árvore de arquivos
        self._model = QFileSystemModel()
        self._model.setFilter(
            QDir.Filter.AllDirs
            | QDir.Filter.Files
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Hidden
        )

        # Proxy pra filtrar por nome via search_input. Recursive: True
        # faz pais aparecerem se algum descendente match. Note: só pega
        # nós já carregados pelo FileSystemModel (que é lazy).
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setRecursiveFilteringEnabled(True)

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
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
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        # Esconde colunas extras (size, type, date) — só o nome.
        for col in (1, 2, 3):
            self._tree.setColumnHidden(col, True)
        # Coluna 0 expande pra largura total
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        # Stack: empty placeholder vs tree. Switch baseado em ter workspace.
        from PySide6.QtWidgets import QStackedWidget as _QSW
        self._stack = _QSW()
        self._stack.addWidget(self._tree)

        # Empty state: ícone grande + texto explicativo, centralizado.
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(20, 40, 20, 20)
        ev.setSpacing(10)
        ev.addStretch(1)
        big_icon = QLabel()
        big_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big_icon.setPixmap(
            ic("fa5s.folder-open", color="#3a3a3a").pixmap(QSize(48, 48))
        )
        ev.addWidget(big_icon)
        title = QLabel("Nenhum workspace selecionado")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #9aa0a6; font-size: 12px; font-weight: 600;")
        ev.addWidget(title)
        hint = QLabel(
            "Escolha um workspace na barra lateral pra navegar seus arquivos."
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #707070; font-size: 11px;")
        ev.addWidget(hint)
        ev.addStretch(2)
        self._empty = empty
        self._stack.addWidget(empty)
        layout.addWidget(self._stack, stretch=1)
        # Inicia em empty (sem workspace)
        self._stack.setCurrentWidget(empty)

    def set_workspace(self, workspace: Workspace | None) -> None:
        """Aponta a árvore pra primeira pasta do workspace."""
        self._workspace = workspace
        if workspace is None or not workspace.folders:
            self._root_label.setText("(nenhum workspace selecionado)")
            self._model.setRootPath("")
            self._stack.setCurrentWidget(self._empty)
            return
        root = workspace.folders[0]
        self._root_label.setText(Path(root).name)
        self._root_label.setToolTip(root)
        src_idx = self._model.setRootPath(root)
        self._tree.setRootIndex(self._proxy.mapFromSource(src_idx))
        self._stack.setCurrentWidget(self._tree)

    def _reload(self) -> None:
        # Re-aponta pra mesma pasta — força refresh do filesystem
        self.set_workspace(self._workspace)

    def _on_search_changed(self, text: str) -> None:
        # Filtro recursivo case-insensitive; vazio = mostra tudo
        self._proxy.setFilterFixedString(text)
        # Expande tudo ao filtrar pra mostrar matches em subpastas
        if text:
            self._tree.expandAll()

    def _on_double_click(self, index: QModelIndex) -> None:
        # index vem do proxy — mapeia pra source antes de pegar o path
        src_idx = self._proxy.mapToSource(index)
        path = self._model.filePath(src_idx)
        if path and not self._model.isDir(src_idx):
            self.open_file_requested.emit(path)

    def _path_at(self, pos) -> tuple[str, bool] | None:
        """Resolve (path, is_dir) do item sob o cursor; None se vazio."""
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return None
        src_idx = self._proxy.mapToSource(index)
        path = self._model.filePath(src_idx)
        if not path:
            return None
        return path, self._model.isDir(src_idx)

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        hit = self._path_at(pos)
        if hit is None:
            return
        path, is_dir = hit
        menu = QMenu(self._tree)
        menu.setStyleSheet(
            "QMenu { background: #1f1f1f; color: #e6e6e6; "
            "border: 1px solid #2c2c2c; }"
            "QMenu::item { padding: 6px 16px; }"
            "QMenu::item:selected { background: #3d6ea8; color: #fff; }"
        )
        # Editor configurável (settings.file_open_command, default "code").
        cmd = "code"
        if self._settings is not None:
            cmd = (getattr(self._settings, "file_open_command", "") or "code").strip() or "code"
        verb = "Abrir pasta" if is_dir else "Abrir/editar arquivo"
        editor_name = "VS Code" if cmd.split()[0] == "code" else cmd.split()[0]
        act_editor = menu.addAction(f"{verb} com {editor_name}")
        act_editor.triggered.connect(lambda: self._open_with_editor(path))
        if not is_dir:
            menu.addSeparator()
            act_internal = menu.addAction("Abrir no editor interno")
            act_internal.triggered.connect(
                lambda: self.open_file_requested.emit(path)
            )
        menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _open_with_editor(self, path: str) -> None:
        from ..launchers import LauncherError, open_file_in_editor
        from ..settings import Settings
        settings = self._settings or Settings.load()
        try:
            open_file_in_editor(path, settings)
        except LauncherError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Abrir arquivo", str(e))
