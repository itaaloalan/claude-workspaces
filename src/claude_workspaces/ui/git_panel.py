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
    fetch as git_fetch,
    has_staged_changes,
    pull_ff_only,
    stage_all,
    stage_file,
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

POLL_INTERVAL_MS = 30_000  # fallback que pega edições do working tree


class GitPanel(QWidget):
    """Status git por pasta do workspace, com:
    - QTreeWidget de repos + arquivos
    - diff inline ao clicar num arquivo
    - context menu (right-click) com Pull/Fetch/Stage/Unstage/Commit
    - auto-refresh via QFileSystemWatcher (.git/index, HEAD, FETCH_HEAD)
      + timer de poll a cada 30s pra pegar edições no working tree
    """

    open_file_requested = Signal(str)  # caminho absoluto

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._statuses: dict[str, GitStatus] = {}  # folder → GitStatus
        self._has_any_repo: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Git</b>"))
        header.addStretch()
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        header.addWidget(self._counter)
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Atualizar (auto a cada 30s + ao detectar mudança no .git)")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

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
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemClicked.connect(self._on_single_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QTreeWidget::item { padding: 3px 4px; color: #d0d0d0; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        split.addWidget(self._tree)

        self._diff = QPlainTextEdit()
        self._diff.setReadOnly(True)
        self._diff.setPlaceholderText(
            "Clique num arquivo pra ver o diff. Double-click abre no editor. "
            "Right-click pra ações git."
        )
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._diff.setFont(mono)
        self._diff.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #d0d0d0; padding: 4px;"
            "}"
        )
        split.addWidget(self._diff)
        split.setSizes([300, 200])
        outer.addWidget(split, stretch=1)

        # Watchers + poll
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_fs_event)
        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)  # debounce após evento do fs
        self._refresh_timer.timeout.connect(self.refresh)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.refresh)

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def has_any_repo(self) -> bool:
        return self._has_any_repo

    # ---------- refresh ----------

    def refresh(self) -> None:
        self._tree.clear()
        self._statuses = {}
        if not self.workspace or not self.workspace.folders:
            self._counter.setText("")
            self._has_any_repo = False
            self._update_watches([])
            return

        total_files = 0
        repo_folders: list[str] = []
        for folder in self.workspace.folders:
            status = get_status(folder)
            self._statuses[folder] = status
            if not status.is_repo:
                continue
            repo_folders.append(folder)
            self._add_repo(folder, status)
            total_files += len(status.files)

        self._has_any_repo = bool(repo_folders)
        if not self._has_any_repo:
            self._counter.setText("")
            placeholder = QTreeWidgetItem(["(nenhuma pasta é repo git)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            self._poll_timer.stop()
        else:
            self._counter.setText(
                "limpo" if total_files == 0 else f"{total_files} alteração(ões)"
            )
            if not self._poll_timer.isActive():
                self._poll_timer.start()

        self._update_watches(repo_folders)

    def _update_watches(self, repo_folders: list[str]) -> None:
        """Refresca o set de paths watched — só .git internals pra evitar
        flood; edições no working tree pegam pelo poll timer."""
        # Remove tudo
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
            # diretório do refs/heads pra captar criação/remoção de branches
            heads = git_dir / "refs" / "heads"
            if heads.is_dir():
                targets.append(str(heads))
        if targets:
            self._watcher.addPaths(targets)

    def _on_fs_event(self, _path: str) -> None:
        # Debounce — múltiplos eventos em rajada viram 1 refresh
        self._refresh_timer.start()

    # ---------- árvore ----------

    def _add_repo(self, folder: str, status: GitStatus) -> None:
        name = Path(folder).name
        ahead_behind = ""
        if status.ahead or status.behind:
            bits = []
            if status.ahead:
                bits.append(f"↑{status.ahead}")
            if status.behind:
                bits.append(f"↓{status.behind}")
            ahead_behind = " " + "".join(bits)
        n = len(status.files)
        marker = "✓ limpo" if n == 0 else f"{n} mudança(s)"
        head = QTreeWidgetItem([f"{name}  ·  {status.branch}{ahead_behind}  ·  {marker}"])
        head.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": folder})
        f = head.font(0)
        f.setBold(True)
        head.setFont(0, f)
        if status.error:
            head.setForeground(0, QBrush(QColor("#d57272")))
            head.setText(0, head.text(0) + f"  ({status.error})")

        for gf in status.files:
            child = self._make_file_item(folder, gf)
            head.addChild(child)
        head.setExpanded(True)
        self._tree.addTopLevelItem(head)

    def _make_file_item(self, folder: str, gf: GitFile) -> QTreeWidgetItem:
        label = gf.label()
        text = f"{gf.status}  {gf.path}"
        item = QTreeWidgetItem([text])
        item.setToolTip(0, f"{label}  ·  {Path(folder) / gf.path}")
        color = STATUS_COLOR.get(label, "#aaa")
        item.setForeground(0, QBrush(QColor(color)))
        f = item.font(0)
        f.setFamily("monospace")
        item.setFont(0, f)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "file",
                "folder": folder,
                "rel_path": gf.path,
                "path": str(Path(folder) / gf.path),
                "is_staged": gf.is_staged,
                "is_unstaged": gf.is_unstaged,
                "is_untracked": gf.is_untracked,
            },
        )
        return item

    # ---------- interação ----------

    def _on_single_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") != "file":
            self._diff.setPlainText("")
            return
        folder = data["folder"]
        rel = data["rel_path"]
        # Se há mudanças staged, prioriza diff staged; senão unstaged.
        # Untracked cai no else do get_diff (mostra conteúdo).
        text = get_diff(folder, rel, staged=data["is_staged"] and not data["is_unstaged"])
        self._diff.setPlainText(text)
        self._highlight_diff_colors()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") == "file":
            self.open_file_requested.emit(data["path"])

    def _highlight_diff_colors(self) -> None:
        """Recoloriza linhas +/- do QPlainTextEdit. Aplica blockFormat
        leve por linha."""
        # Strategy: recolor inteiro com QSyntaxHighlighter seria mais
        # limpo, mas pra um único arquivo já dá pra fazer com a
        # propriedade Foreground de cada linha via cursor.
        from PySide6.QtGui import QTextCharFormat, QTextCursor

        cursor = self._diff.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
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
            cursor.setPosition(block.position() + len(line), QTextCursor.MoveMode.KeepAnchor)
            if line.startswith("+++") or line.startswith("---") or line.startswith("@@") or line.startswith("diff "):
                cursor.setCharFormat(header)
            elif line.startswith("+"):
                cursor.setCharFormat(plus)
            elif line.startswith("-"):
                cursor.setCharFormat(minus)
            block = block.next()
        cursor.endEditBlock()

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        menu = QMenu(self)
        if data.get("type") == "folder":
            folder = data["path"]
            menu.addAction(self._action("⤓ Pull (ff-only)", lambda: self._do_pull(folder)))
            menu.addAction(self._action("⇡⇣ Fetch", lambda: self._do_fetch(folder)))
            menu.addSeparator()
            menu.addAction(self._action("+ Stage tudo", lambda: self._do_stage_all(folder)))
            menu.addAction(self._action("✎ Commit…", lambda: self._do_commit(folder)))
        elif data.get("type") == "file":
            folder = data["folder"]
            rel = data["rel_path"]
            menu.addAction(self._action("Abrir no editor", lambda: self.open_file_requested.emit(data["path"])))
            menu.addSeparator()
            if data.get("is_unstaged") or data.get("is_untracked"):
                menu.addAction(self._action("+ Stage", lambda: self._do_stage(folder, rel)))
            if data.get("is_staged"):
                menu.addAction(self._action("− Unstage", lambda: self._do_unstage(folder, rel)))
        if menu.actions():
            menu.exec_(self._tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _action(text: str, slot) -> QAction:
        a = QAction(text)
        a.triggered.connect(slot)
        return a

    # ---------- ações git ----------

    def _do_pull(self, folder: str) -> None:
        ok, out = pull_ff_only(folder)
        self._notify("Pull", folder, ok, out)
        self.refresh()

    def _do_fetch(self, folder: str) -> None:
        ok, out = git_fetch(folder)
        self._notify("Fetch", folder, ok, out)
        self.refresh()

    def _do_stage(self, folder: str, rel_path: str) -> None:
        ok, out = stage_file(folder, rel_path)
        if not ok:
            self._notify("Stage", folder, ok, out)
        self.refresh()

    def _do_unstage(self, folder: str, rel_path: str) -> None:
        ok, out = unstage_file(folder, rel_path)
        if not ok:
            self._notify("Unstage", folder, ok, out)
        self.refresh()

    def _do_stage_all(self, folder: str) -> None:
        ok, out = stage_all(folder)
        if not ok:
            self._notify("Stage tudo", folder, ok, out)
        self.refresh()

    def _do_commit(self, folder: str) -> None:
        if not has_staged_changes(folder):
            reply = QMessageBox.question(
                self,
                "Sem staging",
                "Não há nada em staging. Quer stage-ar tudo agora?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            ok, out = stage_all(folder)
            if not ok:
                self._notify("Stage tudo", folder, ok, out)
                return
        msg, accepted = QInputDialog.getMultiLineText(
            self, "Mensagem do commit", f"Commit em {Path(folder).name}:"
        )
        if not accepted or not msg.strip():
            return
        ok, out = git_commit(folder, msg.strip())
        self._notify("Commit", folder, ok, out)
        self.refresh()

    def _notify(self, action: str, folder: str, ok: bool, output: str) -> None:
        title = f"{action}: OK" if ok else f"{action} falhou"
        body = f"<b>{Path(folder).name}</b><br><pre>{output[:1500]}</pre>"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(body)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.exec()


def open_path_in_editor(path: str, editor_command: str = "code") -> None:
    try:
        subprocess.Popen([editor_command, path])
    except FileNotFoundError:
        log.warning("Editor %r não encontrado", editor_command)
        raise
