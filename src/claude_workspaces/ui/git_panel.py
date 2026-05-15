import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import (
    commit as git_commit,
    delete_untracked,
    discard_unstaged,
    fetch as git_fetch,
    pull_ff_only,
    stage_all,
    stage_file,
    unstage_all,
    unstage_file,
)
from ..git_status import GitFile, GitStatus, get_diff, get_status
from ..models import Workspace


log = logging.getLogger(__name__)


STATUS_COLOR = {
    "modificado": "#e0b86a",
    "mod (idx+ws)": "#e0b86a",
    "adicionado": "#5ac35a",
    "deletado": "#d57272",
    "renomeado": "#7aa6e6",
    "copiado": "#7aa6e6",
    "novo": "#888",
}

POLL_INTERVAL_MS = 30_000

# UserRole keys
T_GROUP = "group"
T_FILE = "file"
T_REPO = "repo"


class GitPanel(QWidget):
    """Painel estilo IntelliJ Commit:
    - QTreeWidget agrupado por repo, com sub-grupos "Changes" e "Unversioned"
    - Cada arquivo tem checkbox; o commit usa só os marcados
    - Área de commit no rodapé (mensagem multilinha + botão Commit)
    - Diff inline opcional (toggle no header)
    - Auto-refresh via QFileSystemWatcher + poll a cada 30s
    """

    open_file_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._statuses: dict[str, GitStatus] = {}
        self._has_any_repo: bool = False
        self._diff_visible: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Toolbar topo
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 2, 2, 2)
        toolbar.setSpacing(2)
        self._make_toolbar(toolbar)
        outer.addLayout(toolbar)

        # Splitter vertical: tree em cima, diff embaixo (oculto por padrão)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(True)
        split.setHandleWidth(6)
        split.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QTreeWidget::item { padding: 2px 4px; color: #d0d0d0; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_single_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        split.addWidget(self._tree)

        self._diff = QPlainTextEdit()
        self._diff.setReadOnly(True)
        self._diff.setPlaceholderText("Clique num arquivo pra ver o diff.")
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._diff.setFont(mono)
        self._diff.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #d0d0d0; padding: 4px;"
            "}"
        )
        self._diff.setVisible(False)
        split.addWidget(self._diff)
        split.setSizes([400, 0])
        self._tree_diff_split = split
        outer.addWidget(split, stretch=1)

        # Área de commit
        commit_area = self._build_commit_area()
        outer.addWidget(commit_area)

        # Watchers + poll
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._schedule_refresh)
        self._watcher.directoryChanged.connect(self._schedule_refresh)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self.refresh)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.refresh)

    # ---------- construção ----------

    def _make_toolbar(self, layout: QHBoxLayout) -> None:
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        layout.addWidget(self._counter)
        layout.addStretch()

        btn_css = (
            "QPushButton { background: transparent; color: #aaa; "
            "border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #6aa9e0; border-color: #3d6ea8; }"
            "QPushButton:disabled { color: #444; }"
        )

        def _btn(text: str, tooltip: str, slot) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setStyleSheet(btn_css)
            b.clicked.connect(slot)
            return b

        layout.addWidget(_btn("↻", "Atualizar", self.refresh))
        layout.addWidget(_btn("⇡⇣", "Fetch (todos os repos)", self._do_fetch_all))
        layout.addWidget(_btn("⤓", "Pull ff-only (todos os repos)", self._do_pull_all))
        self._toggle_diff_btn = _btn("👁", "Mostrar / esconder diff", self._toggle_diff)
        layout.addWidget(self._toggle_diff_btn)

    def _build_commit_area(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(4)

        self._msg = QPlainTextEdit()
        self._msg.setPlaceholderText("Mensagem do commit…")
        self._msg.setFixedHeight(56)
        self._msg.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 4px; color: #e6e6e6; padding: 4px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        v.addWidget(self._msg)

        bottom = QHBoxLayout()
        self._commit_btn = QPushButton("Commit")
        self._commit_btn.setStyleSheet(
            "QPushButton {"
            "  background: #3d6ea8; color: #fff;"
            "  border: 0; border-radius: 4px; padding: 4px 14px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a82c5; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )
        self._commit_btn.clicked.connect(self._do_commit)
        bottom.addWidget(self._commit_btn)
        bottom.addStretch()
        v.addLayout(bottom)
        return box

    # ---------- workspace ----------

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def has_any_repo(self) -> bool:
        return self._has_any_repo

    # ---------- refresh ----------

    def _schedule_refresh(self, *_args) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        # Preserva o estado de checked dos arquivos (rel_path) por repo
        prev_unchecked: dict[str, set[str]] = {}
        for i in range(self._tree.topLevelItemCount()):
            repo_item = self._tree.topLevelItem(i)
            data = repo_item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") != T_REPO:
                continue
            folder = data["folder"]
            unchecked: set[str] = set()
            self._collect_unchecked_files(repo_item, unchecked)
            prev_unchecked[folder] = unchecked

        self._tree.blockSignals(True)
        self._tree.clear()
        self._statuses = {}

        if not self.workspace or not self.workspace.folders:
            self._counter.setText("")
            self._has_any_repo = False
            self._update_watches([])
            self._tree.blockSignals(False)
            self._update_commit_button()
            return

        repo_folders: list[str] = []
        total_files = 0
        for folder in self.workspace.folders:
            status = get_status(folder)
            self._statuses[folder] = status
            if not status.is_repo:
                continue
            repo_folders.append(folder)
            self._add_repo(folder, status, prev_unchecked.get(folder, set()))
            total_files += len(status.files)

        self._has_any_repo = bool(repo_folders)
        if not self._has_any_repo:
            placeholder = QTreeWidgetItem(["(nenhuma pasta é repo git)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            self._counter.setText("")
            self._poll_timer.stop()
        else:
            self._counter.setText(
                "limpo" if total_files == 0 else f"{total_files} alteração(ões)"
            )
            if not self._poll_timer.isActive():
                self._poll_timer.start()

        self._tree.blockSignals(False)
        self._update_watches(repo_folders)
        self._update_commit_button()

    def _collect_unchecked_files(self, parent: QTreeWidgetItem, out: set[str]) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Unchecked:
                    out.add(data["rel_path"])
            else:
                self._collect_unchecked_files(child, out)

    def _update_watches(self, repo_folders: list[str]) -> None:
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        targets: list[str] = []
        for folder in repo_folders:
            git_dir = Path(folder) / ".git"
            if not git_dir.exists():
                continue
            for name in ("index", "HEAD", "FETCH_HEAD", "ORIG_HEAD"):
                f = git_dir / name
                if f.exists():
                    targets.append(str(f))
            heads = git_dir / "refs" / "heads"
            if heads.is_dir():
                targets.append(str(heads))
        if targets:
            self._watcher.addPaths(targets)

    # ---------- árvore ----------

    def _add_repo(
        self,
        folder: str,
        status: GitStatus,
        prev_unchecked: set[str],
    ) -> None:
        name = Path(folder).name
        ahead_behind = ""
        if status.ahead or status.behind:
            bits = []
            if status.ahead:
                bits.append(f"↑{status.ahead}")
            if status.behind:
                bits.append(f"↓{status.behind}")
            ahead_behind = " " + "".join(bits)
        marker = "✓ limpo" if not status.files else f"{len(status.files)} mudança(s)"
        repo_item = QTreeWidgetItem(
            [f"{name}  ·  {status.branch}{ahead_behind}  ·  {marker}"]
        )
        repo_item.setData(
            0, Qt.ItemDataRole.UserRole, {"type": T_REPO, "folder": folder}
        )
        f = repo_item.font(0)
        f.setBold(True)
        repo_item.setFont(0, f)
        if status.error:
            repo_item.setForeground(0, QBrush(QColor("#d57272")))
            repo_item.setText(0, repo_item.text(0) + f"  ({status.error})")

        # Agrupar em Changes / Unversioned
        changes: list[GitFile] = []
        untracked: list[GitFile] = []
        for gf in status.files:
            if gf.is_untracked:
                untracked.append(gf)
            else:
                changes.append(gf)

        if changes:
            grp = self._make_group_item(folder, "Changes", len(changes))
            repo_item.addChild(grp)
            for gf in changes:
                child = self._make_file_item(folder, gf, prev_unchecked)
                grp.addChild(child)
            grp.setExpanded(True)
        if untracked:
            grp = self._make_group_item(folder, "Unversioned Files", len(untracked))
            repo_item.addChild(grp)
            for gf in untracked:
                child = self._make_file_item(folder, gf, prev_unchecked)
                grp.addChild(child)
            grp.setExpanded(True)

        repo_item.setExpanded(True)
        self._tree.addTopLevelItem(repo_item)

    def _make_group_item(self, folder: str, name: str, count: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"{name}  ({count})"])
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        item.setForeground(0, QBrush(QColor("#bbb")))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"type": T_GROUP, "folder": folder, "name": name},
        )
        return item

    def _make_file_item(
        self,
        folder: str,
        gf: GitFile,
        prev_unchecked: set[str],
    ) -> QTreeWidgetItem:
        rel = gf.path
        parent_path = ""
        name = rel
        if "/" in rel:
            parent_path, name = rel.rsplit("/", 1)
        text = f"{gf.status}  {name}"
        if parent_path:
            text += f"   {parent_path}"
        item = QTreeWidgetItem([text])
        color = STATUS_COLOR.get(gf.label(), "#aaa")
        item.setForeground(0, QBrush(QColor(color)))
        mono = item.font(0)
        mono.setFamily("monospace")
        item.setFont(0, mono)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check_state = (
            Qt.CheckState.Unchecked
            if rel in prev_unchecked
            else Qt.CheckState.Checked
        )
        item.setCheckState(0, check_state)
        item.setToolTip(0, f"{gf.label()}  ·  {Path(folder) / rel}")
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": T_FILE,
                "folder": folder,
                "rel_path": rel,
                "path": str(Path(folder) / rel),
                "is_staged": gf.is_staged,
                "is_unstaged": gf.is_unstaged,
                "is_untracked": gf.is_untracked,
            },
        )
        return item

    # ---------- interação ----------

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int) -> None:
        self._update_commit_button()

    def _on_single_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") != T_FILE:
            return
        if not self._diff_visible:
            return
        folder = data["folder"]
        rel = data["rel_path"]
        text = get_diff(folder, rel, staged=data["is_staged"] and not data["is_unstaged"])
        self._diff.setPlainText(text)
        self._highlight_diff_colors()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") == T_FILE:
            self.open_file_requested.emit(data["path"])

    def _highlight_diff_colors(self) -> None:
        from PySide6.QtGui import QTextCharFormat, QTextCursor

        cursor = self._diff.textCursor()
        cursor.beginEditBlock()
        plus = QTextCharFormat()
        plus.setForeground(QColor("#5ac35a"))
        minus = QTextCharFormat()
        minus.setForeground(QColor("#d57272"))
        header = QTextCharFormat()
        header.setForeground(QColor("#7aa6e6"))
        block = self._diff.document().firstBlock()
        while block.isValid():
            line = block.text()
            cursor.setPosition(block.position())
            cursor.setPosition(
                block.position() + len(line), QTextCursor.MoveMode.KeepAnchor
            )
            if (
                line.startswith("+++")
                or line.startswith("---")
                or line.startswith("@@")
                or line.startswith("diff ")
            ):
                cursor.setCharFormat(header)
            elif line.startswith("+"):
                cursor.setCharFormat(plus)
            elif line.startswith("-"):
                cursor.setCharFormat(minus)
            block = block.next()
        cursor.endEditBlock()

    def _toggle_diff(self) -> None:
        self._diff_visible = not self._diff_visible
        self._diff.setVisible(self._diff_visible)
        if self._diff_visible:
            self._tree_diff_split.setSizes([300, 200])
        else:
            self._tree_diff_split.setSizes([400, 0])

    # ---------- collecting checked files ----------

    def _collect_checked_files(self) -> dict[str, list[str]]:
        """Devolve {folder: [rel_path, ...]} pra cada repo com arquivos marcados."""
        out: dict[str, list[str]] = {}
        for i in range(self._tree.topLevelItemCount()):
            repo = self._tree.topLevelItem(i)
            data = repo.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") != T_REPO:
                continue
            folder = data["folder"]
            files: list[str] = []
            self._walk_collect_checked(repo, files)
            if files:
                out[folder] = files
        return out

    def _walk_collect_checked(
        self, parent: QTreeWidgetItem, out: list[str]
    ) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.append(data["rel_path"])
            else:
                self._walk_collect_checked(child, out)

    def _update_commit_button(self) -> None:
        checked = self._collect_checked_files()
        total = sum(len(v) for v in checked.values())
        self._commit_btn.setEnabled(total > 0)
        self._commit_btn.setText(
            "Commit" if total == 0 else f"Commit ({total})"
        )

    # ---------- context menu ----------

    def _on_context_menu(self, pos: QPoint) -> None:
        items = self._tree.selectedItems()
        clicked = self._tree.itemAt(pos)
        if not items and clicked is not None:
            items = [clicked]
        if not items:
            return

        menu = QMenu(self)
        # Classifica os items selecionados
        file_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_FILE
        ]
        group_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_GROUP
        ]
        repo_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_REPO
        ]

        if file_items:
            self._build_file_menu(menu, file_items)
        elif group_items:
            self._build_group_menu(menu, group_items)
        elif repo_items:
            self._build_repo_menu(menu, repo_items)

        if menu.actions():
            menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _build_file_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        # Pega dados consolidados
        first_data = items[0].data(0, Qt.ItemDataRole.UserRole)
        any_untracked = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_untracked")
            for i in items
        )
        any_unstaged = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_unstaged")
            for i in items
        )
        any_staged = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_staged")
            for i in items
        )
        n = len(items)
        suffix = "" if n == 1 else f" ({n} arquivos)"

        if len(items) == 1:
            menu.addAction(
                self._action(
                    "Abrir no editor",
                    lambda: self.open_file_requested.emit(first_data["path"]),
                )
            )
            menu.addSeparator()

        if any_untracked or any_unstaged:
            menu.addAction(
                self._action(f"+ Add (stage){suffix}", lambda: self._stage_items(items))
            )
        if any_staged:
            menu.addAction(
                self._action(f"− Unstage{suffix}", lambda: self._unstage_items(items))
            )

        menu.addSeparator()
        if any_unstaged:
            menu.addAction(
                self._action(
                    f"↶ Rollback mudanças{suffix}",
                    lambda: self._rollback_items(items),
                )
            )
        if any_untracked:
            menu.addAction(
                self._action(
                    f"✕ Deletar arquivo{suffix}",
                    lambda: self._delete_items(items),
                )
            )

    def _build_group_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        group_name = items[0].data(0, Qt.ItemDataRole.UserRole).get("name", "")
        folder = items[0].data(0, Qt.ItemDataRole.UserRole).get("folder", "")
        if "Unversioned" in group_name:
            menu.addAction(
                self._action("+ Add todos", lambda: self._stage_group(items[0]))
            )
        elif "Changes" in group_name:
            menu.addAction(
                self._action("+ Stage todos", lambda: self._stage_group(items[0]))
            )
            menu.addAction(
                self._action("− Unstage todos", lambda: self._unstage_group(items[0]))
            )
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "↶ Rollback todos",
                    lambda: self._rollback_group(items[0]),
                )
            )

    def _build_repo_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        folder = items[0].data(0, Qt.ItemDataRole.UserRole).get("folder", "")
        menu.addAction(
            self._action("⤓ Pull (ff-only)", lambda: self._do_pull_one(folder))
        )
        menu.addAction(
            self._action("⇡⇣ Fetch", lambda: self._do_fetch_one(folder))
        )
        menu.addSeparator()
        menu.addAction(
            self._action("+ Stage tudo", lambda: stage_all(folder) and self.refresh())
        )
        menu.addAction(
            self._action(
                "− Unstage tudo", lambda: unstage_all(folder) and self.refresh()
            )
        )
        menu.addSeparator()
        from pathlib import Path
        menu.addAction(
            self._action(
                "📁 Abrir pasta",
                lambda: subprocess.Popen(["xdg-open", folder]),
            )
        )

    @staticmethod
    def _action(text: str, slot) -> QAction:
        a = QAction(text)
        a.triggered.connect(slot)
        return a

    # ---------- handlers do menu ----------

    def _stage_items(self, items: list[QTreeWidgetItem]) -> None:
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = stage_file(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Stage", "?", False, "\n".join(errors))
        self.refresh()

    def _unstage_items(self, items: list[QTreeWidgetItem]) -> None:
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = unstage_file(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Unstage", "?", False, "\n".join(errors))
        self.refresh()

    def _rollback_items(self, items: list[QTreeWidgetItem]) -> None:
        names = [i.data(0, Qt.ItemDataRole.UserRole)["rel_path"] for i in items]
        reply = QMessageBox.question(
            self,
            "Rollback de mudanças",
            "Vai descartar mudanças locais (irreversível) em:\n\n"
            + "\n".join(names[:20])
            + (f"\n... e mais {len(names)-20}" if len(names) > 20 else "")
            + "\n\nContinuar?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = discard_unstaged(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Rollback", "?", False, "\n".join(errors))
        self.refresh()

    def _delete_items(self, items: list[QTreeWidgetItem]) -> None:
        names = [i.data(0, Qt.ItemDataRole.UserRole)["rel_path"] for i in items]
        reply = QMessageBox.question(
            self,
            "Deletar arquivos untracked",
            "Vai apagar do disco (irreversível):\n\n"
            + "\n".join(names[:20])
            + (f"\n... e mais {len(names)-20}" if len(names) > 20 else "")
            + "\n\nContinuar?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = delete_untracked(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Delete", "?", False, "\n".join(errors))
        self.refresh()

    def _collect_group_files(self, group_item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        return [group_item.child(i) for i in range(group_item.childCount())]

    def _stage_group(self, group_item: QTreeWidgetItem) -> None:
        self._stage_items(self._collect_group_files(group_item))

    def _unstage_group(self, group_item: QTreeWidgetItem) -> None:
        self._unstage_items(self._collect_group_files(group_item))

    def _rollback_group(self, group_item: QTreeWidgetItem) -> None:
        self._rollback_items(self._collect_group_files(group_item))

    def _do_fetch_one(self, folder: str) -> None:
        ok, out = git_fetch(folder)
        self._notify("Fetch", folder, ok, out)
        self.refresh()

    def _do_pull_one(self, folder: str) -> None:
        ok, out = pull_ff_only(folder)
        self._notify("Pull", folder, ok, out)
        self.refresh()

    # ---------- ações git ----------

    def _do_commit(self) -> None:
        checked = self._collect_checked_files()
        if not checked:
            return
        message = self._msg.toPlainText().strip()
        if not message:
            QMessageBox.warning(
                self,
                "Mensagem vazia",
                "Escreva uma mensagem de commit antes.",
            )
            self._msg.setFocus()
            return

        if len(checked) > 1:
            reply = QMessageBox.question(
                self,
                "Múltiplos repos",
                f"Vai commitar em {len(checked)} repos com a mesma mensagem. Confirma?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        errors: list[str] = []
        for folder, files in checked.items():
            # 1. Reset staging area pro estado limpo
            subprocess.run(
                ["git", "reset", "HEAD", "--"],
                cwd=folder,
                capture_output=True,
                timeout=30,
            )
            # 2. Stage só os arquivos marcados
            stage_failed = False
            for rel in files:
                ok, out = stage_file(folder, rel)
                if not ok:
                    errors.append(f"{Path(folder).name}: stage {rel} falhou — {out}")
                    stage_failed = True
                    break
            if stage_failed:
                continue
            # 3. Commit
            ok, out = git_commit(folder, message)
            if not ok:
                errors.append(f"{Path(folder).name}: commit falhou — {out}")

        if errors:
            QMessageBox.warning(self, "Erros no commit", "\n\n".join(errors)[:2000])
        else:
            self._msg.clear()
        self.refresh()

    def _do_fetch_all(self) -> None:
        if not self.workspace:
            return
        results = []
        for folder in self.workspace.folders:
            if folder not in self._statuses or not self._statuses[folder].is_repo:
                continue
            ok, out = git_fetch(folder)
            results.append(f"{Path(folder).name}: {'OK' if ok else out[:200]}")
        if results:
            QMessageBox.information(self, "Fetch", "\n".join(results)[:2000])
        self.refresh()

    def _do_pull_all(self) -> None:
        if not self.workspace:
            return
        results = []
        for folder in self.workspace.folders:
            if folder not in self._statuses or not self._statuses[folder].is_repo:
                continue
            ok, out = pull_ff_only(folder)
            results.append(f"{Path(folder).name}: {'OK' if ok else out[:200]}")
        if results:
            QMessageBox.information(self, "Pull", "\n".join(results)[:2000])
        self.refresh()


def open_path_in_editor(path: str, editor_command: str = "code") -> None:
    try:
        subprocess.Popen([editor_command, path])
    except FileNotFoundError:
        log.warning("Editor %r não encontrado", editor_command)
        raise
