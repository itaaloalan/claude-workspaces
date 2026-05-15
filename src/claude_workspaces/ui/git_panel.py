import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_status import GitFile, GitStatus, get_status
from ..models import Workspace


log = logging.getLogger(__name__)


# Cores por tipo de mudança — espelham mais ou menos o que git CLI mostra
STATUS_COLOR = {
    "modificado": "#e0b86a",      # amarelo
    "mod (idx+ws)": "#e0b86a",
    "adicionado": "#5ac35a",      # verde
    "deletado": "#d57272",        # vermelho
    "renomeado": "#7aa6e6",       # azul
    "copiado": "#7aa6e6",
    "novo": "#888",               # cinza (untracked)
}


class GitPanel(QWidget):
    """Mostra branch + status porcelain de cada pasta do workspace.
    Double-click num arquivo emite open_file_requested com o caminho
    absoluto pra MainWindow abrir no editor configurado."""

    open_file_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None

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
        refresh_btn.setToolTip("Atualizar (também roda automaticamente ao trocar workspace)")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QTreeWidget::item { padding: 3px 4px; color: #d0d0d0; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._tree, stretch=1)

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def refresh(self) -> None:
        self._tree.clear()
        if not self.workspace or not self.workspace.folders:
            self._counter.setText("")
            placeholder = QTreeWidgetItem(["(sem pastas)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            return

        total_files = 0
        repos = 0
        for folder in self.workspace.folders:
            status = get_status(folder)
            if not status.is_repo:
                item = QTreeWidgetItem([f"{Path(folder).name}  · não é repo git"])
                item.setForeground(0, QBrush(QColor("#666")))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self._tree.addTopLevelItem(item)
                continue
            repos += 1
            self._add_repo(folder, status)
            total_files += len(status.files)

        if total_files == 0 and repos > 0:
            self._counter.setText("limpo")
        elif repos == 0:
            self._counter.setText("")
        else:
            self._counter.setText(f"{total_files} alteração(ões)")

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
        # Monospace pro alinhamento do código de status
        f = item.font(0)
        f.setFamily("monospace")
        item.setFont(0, f)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"type": "file", "path": str(Path(folder) / gf.path)},
        )
        return item

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data.get("type") == "file":
            self.open_file_requested.emit(data["path"])
        elif data.get("type") == "folder":
            # Abrir o diretório no gerenciador de arquivos? Por enquanto
            # não fazemos nada — o usuário pode usar o card de pasta acima
            pass


def open_path_in_editor(path: str, editor_command: str = "code") -> None:
    """Abre o arquivo (ou pasta) no editor configurado. Caller passa o
    comando vindo de Settings (ex: 'code', 'idea')."""
    try:
        subprocess.Popen([editor_command, path])
    except FileNotFoundError:
        log.warning("Editor %r não encontrado", editor_command)
        raise
