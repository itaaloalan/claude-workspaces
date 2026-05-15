from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..models import Workspace


class WorkspaceDialog(QDialog):
    def __init__(self, workspace: Workspace | None = None, parent=None) -> None:
        super().__init__(parent)
        self._original = workspace
        self.setWindowTitle("Editar workspace" if workspace else "Novo workspace")
        self.resize(560, 460)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(workspace.name if workspace else "")
        form.addRow("Nome:", self.name_edit)

        self.desc_edit = QTextEdit(workspace.description if workspace else "")
        self.desc_edit.setMaximumHeight(80)
        form.addRow("Descrição:", self.desc_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Pastas (a primeira é a principal — vira o cwd do Claude):"))
        self.folders_list = QListWidget()
        if workspace:
            self.folders_list.addItems(workspace.folders)
        layout.addWidget(self.folders_list)

        folder_actions = QHBoxLayout()
        add_btn = QPushButton("Adicionar pasta")
        add_btn.clicked.connect(self.add_folder)
        remove_btn = QPushButton("Remover selecionada")
        remove_btn.clicked.connect(self.remove_folder)
        up_btn = QPushButton("Mover ↑")
        up_btn.clicked.connect(lambda: self.move_selected(-1))
        down_btn = QPushButton("Mover ↓")
        down_btn.clicked.connect(lambda: self.move_selected(1))
        folder_actions.addWidget(add_btn)
        folder_actions.addWidget(remove_btn)
        folder_actions.addWidget(up_btn)
        folder_actions.addWidget(down_btn)
        folder_actions.addStretch()
        layout.addLayout(folder_actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Selecionar pasta")
        if path:
            self.folders_list.addItem(path)

    def remove_folder(self) -> None:
        for item in self.folders_list.selectedItems():
            self.folders_list.takeItem(self.folders_list.row(item))

    def move_selected(self, delta: int) -> None:
        row = self.folders_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.folders_list.count():
            return
        item = self.folders_list.takeItem(row)
        self.folders_list.insertItem(new_row, item)
        self.folders_list.setCurrentRow(new_row)

    def workspace(self) -> Workspace:
        folders = [self.folders_list.item(i).text() for i in range(self.folders_list.count())]
        if self._original is not None:
            # Preserva id e tarefas — edição não invalida referências
            # existentes em _terminal_areas / _running_counts da MainWindow
            return Workspace(
                id=self._original.id,
                name=self.name_edit.text().strip(),
                folders=folders,
                description=self.desc_edit.toPlainText().strip(),
                tasks=list(self._original.tasks),
            )
        return Workspace(
            name=self.name_edit.text().strip(),
            folders=folders,
            description=self.desc_edit.toPlainText().strip(),
        )
