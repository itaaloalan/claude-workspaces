from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..launchers import LauncherError, launch_claude, launch_konsole, launch_vscode
from ..models import Workspace


class WorkspaceCard(QFrame):
    edit_requested = Signal(Workspace)
    delete_requested = Signal(Workspace)

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self.workspace = workspace
        self.setObjectName("workspaceCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#workspaceCard { border: 1px solid #3a3a3a; border-radius: 8px; padding: 10px; }"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        header = QHBoxLayout()
        name = QLabel(f"<b>{workspace.name}</b>")
        header.addWidget(name)
        header.addStretch()

        edit_btn = QPushButton("Editar")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(workspace))
        del_btn = QPushButton("Remover")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(workspace))
        header.addWidget(edit_btn)
        header.addWidget(del_btn)
        layout.addLayout(header)

        if workspace.description:
            desc = QLabel(workspace.description)
            desc.setWordWrap(True)
            layout.addWidget(desc)

        folders_text = "\n".join(f"• {f}" for f in workspace.folders) or "(sem pastas)"
        folders = QLabel(folders_text)
        folders.setStyleSheet("color: #888;")
        layout.addWidget(folders)

        actions = QHBoxLayout()
        claude_btn = QPushButton("Abrir Claude")
        claude_btn.clicked.connect(self._launch_claude)
        konsole_btn = QPushButton("Abrir Konsole")
        konsole_btn.clicked.connect(self._launch_konsole)
        vscode_btn = QPushButton("Abrir VSCode")
        vscode_btn.clicked.connect(self._launch_vscode)
        actions.addWidget(claude_btn)
        actions.addWidget(konsole_btn)
        actions.addWidget(vscode_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def _launch_claude(self) -> None:
        try:
            launch_claude(self.workspace)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Falha ao abrir Claude", str(e))

    def _launch_konsole(self) -> None:
        try:
            launch_konsole(self.workspace)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Falha ao abrir Konsole", str(e))

    def _launch_vscode(self) -> None:
        try:
            launch_vscode(self.workspace)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Falha ao abrir VSCode", str(e))
