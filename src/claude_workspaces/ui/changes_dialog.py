"""Diálogo "Changes" — revisão das mudanças não commitadas do workspace.

Tem o mesmo visual do painel de arquivos do diálogo de Push (uma seção por
repositório, arquivos agrupados por pasta), mas compara HEAD → working tree:
duplo clique abre o diff lado-a-lado das mudanças ainda não commitadas e o
botão direito abre o arquivo no editor. Não há ação de push — só revisão.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import WORKTREE
from . import theme
from .push_dialog import (
    _GHOST_QSS,
    _STATUS_COLOR,
    _STATUS_LABEL,
    _TREE_QSS,
    _bold,
    _expand_all,
)


class ChangesDialog(QDialog):
    """Mostra as mudanças não commitadas por repo; diff HEAD → working tree."""

    def __init__(
        self,
        repos: list[tuple[str, str, list[tuple[str, str]]]],
        parent: QWidget | None = None,
    ) -> None:
        """`repos` = lista de (nome, pasta, [(status, rel_path), ...])."""
        super().__init__(parent)
        # Só repos com algum arquivo alterado.
        self._repos = [r for r in repos if r[2]]
        self._file_entries: list[dict] = []
        self.setWindowTitle("Changes — mudanças não commitadas")
        self.setMinimumSize(720, 480)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_PANEL}; color: #e6e6e6; }}"
            "QLabel { color: #d0d0d0; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        outer.addWidget(self._build_files_tree(), stretch=1)
        outer.addLayout(self._build_buttons())

    # ---------- árvore de arquivos por pasta ----------

    def _build_files_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setStyleSheet(_TREE_QSS)
        tree.setToolTip(
            "Duplo clique abre o diff lado-a-lado · botão direito abre no editor"
        )
        tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree: self._on_files_context_menu(t, pos)
        )
        for name, folder, files in self._repos:
            root = QTreeWidgetItem([f"{name}  {len(files)} files"])
            _bold(root)
            root.setForeground(0, QBrush(QColor("#bbb")))
            self._populate_dir_tree(root, folder, files)
            tree.addTopLevelItem(root)
            _expand_all(root)
        return tree

    def _on_file_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            item.setExpanded(not item.isExpanded())
            return
        try:
            from .diff_viewer_dialog import DiffViewerDialog

            DiffViewerDialog(
                self._file_entries, index=data.get("index", 0), parent=self
            ).exec()
        except Exception as e:  # nunca falhar em silêncio no duplo clique
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Falha ao abrir o diff",
                f"{data.get('path', '')}\n\n{type(e).__name__}: {e}",
            )

    def _on_files_context_menu(self, tree: QTreeWidget, pos: QPoint) -> None:
        item = tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:  # nó de pasta/repo
            return
        menu = QMenu(self)
        from ..settings import Settings

        cmd = (Settings.load().file_open_command or "code").strip() or "code"
        editor = "VS Code" if cmd.split()[0] == "code" else cmd.split()[0]

        act_diff = QAction("👁 Ver diff lado-a-lado", self)
        act_diff.triggered.connect(lambda: self._on_file_double_clicked(item, 0))
        menu.addAction(act_diff)

        act_open = QAction(f"⧉ Abrir com {editor}", self)
        act_open.triggered.connect(lambda: self._open_in_editor(data["full"]))
        menu.addAction(act_open)

        menu.exec(tree.viewport().mapToGlobal(pos))

    def _open_in_editor(self, full_path: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        from ..services.system_open import open_in_editor
        from ..settings import Settings

        cmd = (Settings.load().file_open_command or "code").strip() or "code"
        try:
            open_in_editor(full_path, cmd)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Falha ao abrir no editor",
                f"{full_path}\n\n{type(e).__name__}: {e}",
            )

    def _populate_dir_tree(
        self, root: QTreeWidgetItem, folder: str, files: list[tuple[str, str]]
    ) -> None:
        """Agrupa arquivos por diretório, criando nós de pasta com contagem."""
        dir_nodes: dict[str, QTreeWidgetItem] = {"": root}

        def ensure_dir(path: str) -> QTreeWidgetItem:
            if path in dir_nodes:
                return dir_nodes[path]
            parent_path, _, name = path.rpartition("/")
            parent = ensure_dir(parent_path)
            node = QTreeWidgetItem([name])
            node.setForeground(0, QBrush(QColor("#cdd3da")))
            parent.addChild(node)
            dir_nodes[path] = node
            return node

        counts: dict[str, int] = {}
        for _status, rel in files:
            parent_path = rel.rpartition("/")[0]
            p = parent_path
            while True:
                counts[p] = counts.get(p, 0) + 1
                if not p:
                    break
                p = p.rpartition("/")[0]

        for status, rel in sorted(files, key=lambda t: t[1]):
            parent_path, _, name = rel.rpartition("/")
            parent = ensure_dir(parent_path)
            code = status[0] if status else ""
            color = _STATUS_COLOR.get(code, "#aaa")
            leaf = QTreeWidgetItem([name])
            leaf.setForeground(0, QBrush(QColor(color)))
            mono = leaf.font(0)
            mono.setFamily("monospace")
            leaf.setFont(0, mono)
            leaf.setToolTip(
                0,
                f"{_STATUS_LABEL.get(code, status)} · {rel}\n"
                "(duplo clique abre o diff)",
            )
            entry = {
                "folder": folder,
                "base": "HEAD",
                "head": WORKTREE,
                "path": rel,
                "full": str(Path(folder) / rel),
                "index": len(self._file_entries),
            }
            self._file_entries.append(entry)
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry)
            parent.addChild(leaf)

        for path, node in dir_nodes.items():
            if node is root:
                continue
            n = counts.get(path, node.childCount())
            node.setText(0, f"{node.text(0)}  {n} files" if n != 1 else node.text(0))

    # ---------- rodapé ----------

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        total = len(self._file_entries)
        info = QLabel(
            f"{total} arquivo(s) alterado(s) em {len(self._repos)} repo(s)"
        )
        info.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(info)
        row.addStretch()
        close_btn = QPushButton("Fechar")
        close_btn.setStyleSheet(_GHOST_QSS)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        return row
