"""Diálogo "Push Commits" no estilo do IntelliJ.

Antes de empurrar pro remote, mostra os commits que vão subir (à esquerda)
e a árvore de arquivos alterados por esses commits (à direita), agrupada por
pasta. Botão Push confirma; Cancel aborta. Suporta multi-repo (uma seção por
repositório) e a opção "Push tags".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import PushPreview, push
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
        # Lista achatada de arquivos na ordem da árvore — usada pra navegação
        # entre arquivos no visualizador de diff.
        self._file_entries: list[dict] = []
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

        # Console com a saída do push — oculto até o usuário disparar o push.
        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setVisible(False)
        self._console.setFixedHeight(150)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._console.setFont(mono)
        self._console.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #d0d0d0; padding: 4px;"
            "}"
        )
        outer.addWidget(self._console)

        self._pushing = False
        self._push_done = False
        outer.addLayout(self._build_buttons())

    # ---------- painel esquerdo: commits ----------

    def _build_commits_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setStyleSheet(_TREE_QSS)
        multi = len(self._previews) > 1
        for pv in self._previews:
            # Nó da branch (com chip ⎇) como pai; commits ficam indentados
            # abaixo, um por linha — como no IntelliJ.
            label = f"⎇ {pv.branch}"
            if multi:
                label = f"{pv.name}  ·  {label}"
            branch_node = QTreeWidgetItem([f"{label}  ({len(pv.commits)})"])
            _bold(branch_node)
            branch_node.setForeground(0, QBrush(QColor(theme.WARNING)))
            tree.addTopLevelItem(branch_node)
            for c in pv.commits:
                item = QTreeWidgetItem([c.subject])
                item.setForeground(0, QBrush(QColor("#d0d0d0")))
                item.setToolTip(
                    0, f"{c.short} · {c.author} · {c.date}\n{c.subject}"
                )
                branch_node.addChild(item)
            branch_node.setExpanded(True)
        return tree

    # ---------- painel direito: arquivos por pasta ----------

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
            # Nó de pasta/repo: alterna expansão (comportamento esperado).
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
            entry = {
                "folder": pv.folder,
                "base": pv.base,
                "head": pv.head,
                "path": rel,
                "full": str(Path(pv.folder) / rel),
                "index": len(self._file_entries),
            }
            self._file_entries.append(entry)
            leaf.setData(0, Qt.ItemDataRole.UserRole, entry)
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

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setStyleSheet(_GHOST_QSS)
        self._cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self._cancel_btn)

        self._push_btn = QPushButton("Push")
        self._push_btn.setStyleSheet(_PRIMARY_QSS)
        self._push_btn.setDefault(True)
        self._push_btn.clicked.connect(self._run_push)
        self._push_btn.setEnabled(bool(self._previews))
        row.addWidget(self._push_btn)
        return row

    # ---------- execução do push + console ----------

    def _on_cancel(self) -> None:
        # Depois do push concluído o "Cancel" vira "Fechar" → fecha aceitando
        # pra o painel saber que houve push e dar refresh.
        if self._push_done:
            self.accept()
        else:
            self.reject()

    def _log(self, text: str, color: str | None = None) -> None:
        if color:
            self._console.appendHtml(
                f"<span style='color:{color}'>{_html(text)}</span>"
            )
        else:
            self._console.appendPlainText(text)
        self._console.verticalScrollBar().setValue(
            self._console.verticalScrollBar().maximum()
        )
        QApplication.processEvents()

    def _run_push(self) -> None:
        if self._pushing or not self._previews:
            return
        self._pushing = True
        self._push_btn.setEnabled(False)
        self.push_tags.setEnabled(False)
        self._console.setVisible(True)
        self._console.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        follow_tags = self.push_tags.isChecked()
        ok_all = True
        try:
            for pv in self._previews:
                label = f"{pv.name} ({pv.branch} → {pv.remote})"
                self._log(f"$ git push {pv.remote} {pv.branch}"
                          + (" --follow-tags" if follow_tags else ""), "#6aa9e0")
                ok_push, out = push(
                    pv.folder,
                    pv.branch,
                    remote=pv.remote,
                    set_upstream=not pv.has_upstream,
                    follow_tags=follow_tags,
                )
                if out.strip():
                    self._log(out.strip())
                if ok_push:
                    self._log(f"✓ {label}: push concluído", theme.SUCCESS)
                else:
                    ok_all = False
                    self._log(f"✗ {label}: push falhou", theme.DANGER)
                self._log("")
        finally:
            QApplication.restoreOverrideCursor()

        self._pushing = False
        self._push_done = True
        self._log(
            "Tudo enviado." if ok_all else "Concluído com erros — revise acima.",
            theme.SUCCESS if ok_all else theme.WARNING,
        )
        # Push não volta a ficar disponível; usuário fecha o diálogo.
        self._cancel_btn.setText("Fechar")
        self._cancel_btn.setDefault(True)

    # ---------- API ----------

    def previews_to_push(self) -> list[PushPreview]:
        return self._previews

    def follow_tags(self) -> bool:
        return self.push_tags.isChecked()


def _html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


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
