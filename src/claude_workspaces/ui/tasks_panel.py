from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Task, Workspace


class TasksPanel(QWidget):
    """Lista de tarefas por workspace. Emite tasks_changed quando o usuário
    cria, marca ou remove uma tarefa, pra que a MainWindow persista o
    workspace inteiro."""

    tasks_changed = Signal(Workspace)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("<b>Atividades (Pendentes)</b>")
        header.addWidget(title)
        header.addStretch()
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        header.addWidget(self._counter)
        outer.addLayout(header)

        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Nova tarefa…")
        self._input.returnPressed.connect(self._add_from_input)
        add_row.addWidget(self._input, stretch=1)
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(32)
        add_btn.setToolTip("Adicionar tarefa (Enter)")
        add_btn.clicked.connect(self._add_from_input)
        add_row.addWidget(add_btn)
        outer.addLayout(add_row)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2c2c2c; border-radius: 6px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #232323; }"
            "QListWidget::item:selected { background: #2d4a6e; }"
        )
        self._list.itemChanged.connect(self._on_item_changed)
        outer.addWidget(self._list, stretch=1)

        footer = QHBoxLayout()
        clear_btn = QPushButton("Limpar concluídas")
        clear_btn.clicked.connect(self._clear_done)
        footer.addWidget(clear_btn)
        del_btn = QPushButton("Remover selecionada")
        del_btn.clicked.connect(self._delete_selected)
        footer.addWidget(del_btn)
        footer.addStretch()
        outer.addLayout(footer)

        QShortcut(QKeySequence.StandardKey.Delete, self._list, self._delete_selected)

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self._refresh()

    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        if self.workspace is None:
            self._counter.setText("")
            self._list.blockSignals(False)
            return
        for task in self.workspace.tasks:
            item = QListWidgetItem(task.title)
            item.setData(Qt.ItemDataRole.UserRole, task.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if task.done else Qt.CheckState.Unchecked
            )
            if task.done:
                f = item.font()
                f.setStrikeOut(True)
                item.setFont(f)
                item.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._refresh_counter()

    def _refresh_counter(self) -> None:
        if self.workspace is None:
            self._counter.setText("")
            return
        total = len(self.workspace.tasks)
        if total == 0:
            self._counter.setText("")
            return
        pending = sum(1 for t in self.workspace.tasks if not t.done)
        self._counter.setText(f"{pending}/{total} pendentes")

    def _add_from_input(self) -> None:
        if self.workspace is None:
            return
        title = self._input.text().strip()
        if not title:
            return
        self.workspace.tasks.append(Task(title=title))
        self._input.clear()
        self._refresh()
        self.tasks_changed.emit(self.workspace)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self.workspace is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        for task in self.workspace.tasks:
            if task.id == task_id:
                task.done = item.checkState() == Qt.CheckState.Checked
                break
        self._refresh()
        self.tasks_changed.emit(self.workspace)

    def _delete_selected(self) -> None:
        if self.workspace is None:
            return
        item = self._list.currentItem()
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.workspace.tasks = [t for t in self.workspace.tasks if t.id != task_id]
        self._refresh()
        self.tasks_changed.emit(self.workspace)

    def _clear_done(self) -> None:
        if self.workspace is None:
            return
        before = len(self.workspace.tasks)
        self.workspace.tasks = [t for t in self.workspace.tasks if not t.done]
        if len(self.workspace.tasks) != before:
            self._refresh()
            self.tasks_changed.emit(self.workspace)
