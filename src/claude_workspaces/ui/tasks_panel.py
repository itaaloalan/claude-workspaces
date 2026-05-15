from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
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
    """TODO list manual por workspace — itens criados pelo usuário ou
    convertidos a partir de uma sessão recente do Claude. Não puxa
    de fontes externas (Linear, GitHub, etc).

    Emite tasks_changed quando há mudança, pra que a MainWindow
    persista o workspace inteiro."""

    tasks_changed = Signal(Workspace)

    FILTER_ALL = "all"
    FILTER_PENDING = "pending"
    FILTER_DONE = "done"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._filter = self.FILTER_PENDING

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("<b>Tarefas</b>")
        title.setToolTip(
            "TODO local por workspace. Criadas manualmente ou a partir "
            "de sessões recentes do Claude (botão → Tarefa no card)."
        )
        header.addWidget(title)
        header.addStretch()
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        header.addWidget(self._counter)
        outer.addLayout(header)

        # Chips de filtro — guardamos pra marcar o default depois de
        # criar a QListWidget (senão setChecked dispara _on_chip_toggled
        # antes do _list existir)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chips: list[QPushButton] = []
        for key, label in [
            (self.FILTER_PENDING, "Pendentes"),
            (self.FILTER_DONE, "Concluídas"),
            (self.FILTER_ALL, "Todas"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("filter_key", key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #aaa;"
                "  border: 1px solid #2c2c2c; border-radius: 12px;"
                "  padding: 2px 10px; font-size: 11px;"
                "}"
                "QPushButton:hover { color: #e6e6e6; border-color: #3d6ea8; }"
                "QPushButton:checked {"
                "  background: #3d6ea8; color: #fff; border-color: #3d6ea8;"
                "}"
            )
            btn.toggled.connect(self._on_chip_toggled)
            self._chip_group.addButton(btn)
            chips.addWidget(btn)
            self._chips.append(btn)
        chips.addStretch()
        outer.addLayout(chips)

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
            "QListWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QListWidget::item {"
            "  padding: 6px 8px; border-bottom: 1px solid #232323;"
            "  color: #d0d0d0;"
            "}"
            "QListWidget::item:hover { background: #2a3142; color: #fff; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
            "QListWidget::item:selected:hover { background: #4a82c5; color: #fff; }"
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

        # Marca o filtro default agora que _list existe
        for btn in self._chips:
            if btn.property("filter_key") == self._filter:
                btn.setChecked(True)
                break

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self._refresh()

    def _on_chip_toggled(self, checked: bool) -> None:
        if not checked:
            return
        btn = self._chip_group.checkedButton()
        if btn is None:
            return
        self._filter = btn.property("filter_key")
        self._refresh()

    def _visible_tasks(self) -> list[Task]:
        if self.workspace is None:
            return []
        if self._filter == self.FILTER_PENDING:
            return [t for t in self.workspace.tasks if not t.done]
        if self._filter == self.FILTER_DONE:
            return [t for t in self.workspace.tasks if t.done]
        return list(self.workspace.tasks)

    def _refresh(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for task in self._visible_tasks():
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
            self._counter.setText("vazio")
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
        # Se o filtro atual oculta nova tarefa (caso "Concluídas"), troca pro
        # "Todas" pra que o usuário veja o que acabou de criar
        if self._filter == self.FILTER_DONE:
            for btn in self._chip_group.buttons():
                if btn.property("filter_key") == self.FILTER_ALL:
                    btn.setChecked(True)
                    break
        else:
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
