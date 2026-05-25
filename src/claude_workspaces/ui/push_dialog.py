"""Diálogo "Push Commits" no estilo do IntelliJ.

Antes de empurrar pro remote, mostra os commits que vão subir (à esquerda)
e a árvore de arquivos alterados por esses commits (à direita), agrupada por
pasta. Botão Push confirma; Cancel aborta. Suporta multi-repo (uma seção por
repositório) e a opção "Push tags".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import PushPreview
from . import theme

# Cor por letra de status do `git diff --name-status`.
_STATUS_COLOR = {
    "A": theme.SUCCESS,
    "M": theme.WARNING,
    "D": theme.DANGER,
    "R": "#7aa6e6",
    "C": "#7aa6e6",
    "T": theme.WARNING,
}
_STATUS_LABEL = {
    "A": "adicionado",
    "M": "modificado",
    "D": "deletado",
    "R": "renomeado",
    "C": "copiado",
    "T": "tipo alterado",
}


class PushCommitsDialog(QDialog):
    """Confirma o push exibindo commits + arquivos. `exec()` Accepted = Push."""

    def __init__(
        self, previews: list[PushPreview], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        # Só repos que de fato têm algo a enviar.
        self._previews = [p for p in previews if not p.error and not p.is_empty]
        remotes = {p.remote for p in self._previews} or {"origin"}
        remote_label = next(iter(remotes)) if len(remotes) == 1 else "remotos"
        self.setWindowTitle(f"Push Commits to {remote_label}")
        self.setMinimumSize(820, 480)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_PANEL}; color: #e6e6e6; }}"
            "QLabel { color: #d0d0d0; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(6)
        split.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )
        split.addWidget(self._build_commits_tree())
        split.addWidget(self._build_files_tree())
        split.setSizes([330, 490])
        outer.addWidget(split, stretch=1)

        outer.addLayout(self._build_buttons())

    # ---------- painel esquerdo: commits ----------

    def _build_commits_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setStyleSheet(_TREE_QSS)
        multi = len(self._previews) > 1
        for pv in self._previews:
            if multi:
                parent = QTreeWidgetItem(
                    [f"{pv.name}  ·  {pv.branch}  ({len(pv.commits)})"]
                )
                _bold(parent)
                parent.setForeground(0, QBrush(QColor("#bbb")))
                tree.addTopLevelItem(parent)
            else:
                parent = None
            for idx, c in enumerate(pv.commits):
                # Primeiro commit (o mais recente, topo) ganha o chip da branch,
                # como no IntelliJ.
                prefix = f"⎇ {pv.branch}  " if (idx == 0 and not multi) else ""
                item = QTreeWidgetItem([f"{prefix}{c.subject}"])
                item.setToolTip(
                    0, f"{c.short} · {c.author} · {c.date}\n{c.subject}"
                )
                if parent is not None:
                    parent.addChild(item)
                else:
                    tree.addTopLevelItem(item)
            if parent is not None:
                parent.setExpanded(True)
        return tree

    # ---------- painel direito: arquivos por pasta ----------

    def _build_files_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setStyleSheet(_TREE_QSS)
        tree.setToolTip("Duplo clique num arquivo abre o diff lado-a-lado")
        tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        for pv in self._previews:
            root = QTreeWidgetItem([f"{pv.name}  {len(pv.files)} files"])
            _bold(root)
            root.setForeground(0, QBrush(QColor("#bbb")))
            self._populate_dir_tree(root, pv, pv.files)
            tree.addTopLevelItem(root)
            _expand_all(root)
        return tree

    def _on_file_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from .diff_viewer_dialog import DiffViewerDialog

        DiffViewerDialog(
            folder=data["folder"],
            base=data["base"],
            head=data["head"],
            path=data["path"],
            base_label=data["base"][:7] if data["base"] else "base",
            head_label="HEAD",
            parent=self,
        ).exec()

    def _populate_dir_tree(
        self, root: QTreeWidgetItem, pv: PushPreview, files: list[tuple[str, str]]
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

        # Conta arquivos por pasta (recursivo) pra anotar "N files".
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
            # Arquivos deletados não têm conteúdo novo pra comparar; ainda
            # assim deixamos abrir (mostra o lado esquerdo).
            leaf.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "folder": pv.folder,
                    "base": pv.base,
                    "head": pv.head,
                    "path": rel,
                },
            )
            parent.addChild(leaf)

        # Anota contagem nos nós de pasta.
        for path, node in dir_nodes.items():
            if node is root:
                continue
            n = counts.get(path, node.childCount())
            node.setText(0, f"{node.text(0)}  {n} files" if n != 1 else node.text(0))

    # ---------- rodapé ----------

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.push_tags = QCheckBox("Push tags")
        self.push_tags.setStyleSheet("QCheckBox { color: #c0c0c0; }")
        row.addWidget(self.push_tags)

        total_commits = sum(len(p.commits) for p in self._previews)
        info = QLabel(
            f"{total_commits} commit(s) em {len(self._previews)} repo(s)"
        )
        info.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(info)

        row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(_GHOST_QSS)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        push = QPushButton("Push")
        push.setStyleSheet(_PRIMARY_QSS)
        push.setDefault(True)
        push.clicked.connect(self.accept)
        push.setEnabled(bool(self._previews))
        row.addWidget(push)
        return row

    # ---------- API ----------

    def previews_to_push(self) -> list[PushPreview]:
        return self._previews

    def follow_tags(self) -> bool:
        return self.push_tags.isChecked()


def _bold(item: QTreeWidgetItem) -> None:
    f = item.font(0)
    f.setBold(True)
    item.setFont(0, f)


def _expand_all(item: QTreeWidgetItem) -> None:
    item.setExpanded(True)
    for i in range(item.childCount()):
        _expand_all(item.child(i))


_TREE_QSS = (
    "QTreeWidget {"
    "  background: #181818; border: 1px solid #2c2c2c;"
    "  border-radius: 6px; color: #e6e6e6;"
    "}"
    "QTreeWidget::item { padding: 2px 4px; color: #d0d0d0; }"
    "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
    "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
)

_PRIMARY_QSS = (
    "QPushButton {"
    "  background: #3d6ea8; color: #fff;"
    "  border: 0; border-radius: 4px; padding: 5px 22px; font-weight: 600;"
    "}"
    "QPushButton:hover { background: #4a82c5; }"
    "QPushButton:disabled { background: #2a2a2a; color: #555; }"
)
_GHOST_QSS = (
    "QPushButton {"
    "  background: #1f1f1f; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 4px; padding: 5px 16px;"
    "}"
    "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
)
