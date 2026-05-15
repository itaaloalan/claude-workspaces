from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace
from ..storage import load_workspaces, save_workspaces
from .workspace_card import WorkspaceCard
from .workspace_dialog import WorkspaceDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claude Workspaces")
        self.resize(960, 640)

        self.workspaces: list[Workspace] = load_workspaces()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("<h2>Workspaces</h2>"))
        toolbar.addStretch()
        add_btn = QPushButton("+ Novo workspace")
        add_btn.clicked.connect(self.add_workspace)
        toolbar.addWidget(add_btn)
        root.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setSpacing(8)
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll)

        self.refresh_cards()

    def refresh_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.workspaces:
            empty = QLabel("Nenhum workspace ainda. Clique em '+ Novo workspace' para começar.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #888; padding: 32px;")
            self.cards_layout.addWidget(empty)
            return

        for ws in self.workspaces:
            card = WorkspaceCard(ws)
            card.edit_requested.connect(self.edit_workspace)
            card.delete_requested.connect(self.delete_workspace)
            self.cards_layout.addWidget(card)

    def add_workspace(self) -> None:
        dialog = WorkspaceDialog(parent=self)
        if dialog.exec():
            ws = dialog.workspace()
            if not ws.name:
                QMessageBox.warning(self, "Workspace inválido", "O nome não pode ficar vazio.")
                return
            self.workspaces.append(ws)
            save_workspaces(self.workspaces)
            self.refresh_cards()

    def edit_workspace(self, workspace: Workspace) -> None:
        dialog = WorkspaceDialog(workspace=workspace, parent=self)
        if dialog.exec():
            updated = dialog.workspace()
            idx = self.workspaces.index(workspace)
            self.workspaces[idx] = updated
            save_workspaces(self.workspaces)
            self.refresh_cards()

    def delete_workspace(self, workspace: Workspace) -> None:
        reply = QMessageBox.question(
            self,
            "Remover workspace",
            f"Remover o workspace '{workspace.name}'?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.workspaces.remove(workspace)
            save_workspaces(self.workspaces)
            self.refresh_cards()
