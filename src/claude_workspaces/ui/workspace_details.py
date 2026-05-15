from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..launchers import (
    IDE_LABEL,
    LauncherError,
    launch_claude,
    launch_ide,
    launch_konsole,
)
from ..models import Workspace
from ..settings import Settings
from ..stacks import STACK_LABEL, STACK_TO_IDE, detect_stacks


class WorkspaceDetailsPanel(QStackedWidget):
    edit_requested = Signal(Workspace)
    delete_requested = Signal(Workspace)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.workspace: Workspace | None = None

        self._empty = self._build_empty_panel()
        self.addWidget(self._empty)

        self._content = self._build_content_panel()
        self.addWidget(self._content)

    def _build_empty_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        msg = QLabel("Selecione um workspace na barra lateral ou crie um novo.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color: #888;")
        layout.addWidget(msg)
        return w

    def _build_content_panel(self) -> QWidget:
        w = QWidget()
        c = QVBoxLayout(w)
        c.setContentsMargins(20, 20, 20, 20)
        c.setSpacing(10)

        self._name = QLabel()
        self._name.setStyleSheet("font-size: 20px; font-weight: bold;")
        c.addWidget(self._name)

        self._stacks = QLabel()
        self._stacks.setStyleSheet("color: #888;")
        c.addWidget(self._stacks)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color: #bbb; margin-top: 4px;")
        c.addWidget(self._desc)

        c.addSpacing(8)
        c.addWidget(QLabel("<b>Pastas</b>"))
        self._folders = QLabel()
        self._folders.setWordWrap(True)
        self._folders.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._folders.setStyleSheet("color: #aaa; font-family: monospace;")
        c.addWidget(self._folders)

        c.addSpacing(12)
        c.addWidget(QLabel("<b>Abrir com</b>"))

        primary_row = QHBoxLayout()
        claude_btn = QPushButton("Abrir Claude")
        claude_btn.clicked.connect(self._launch_claude)
        konsole_btn = QPushButton("Abrir Terminal")
        konsole_btn.clicked.connect(self._launch_konsole)
        primary_row.addWidget(claude_btn)
        primary_row.addWidget(konsole_btn)
        primary_row.addStretch()
        c.addLayout(primary_row)

        self._ide_row_host = QWidget()
        self._ide_row = QHBoxLayout(self._ide_row_host)
        self._ide_row.setContentsMargins(0, 0, 0, 0)
        c.addWidget(self._ide_row_host)

        c.addStretch()

        meta = QHBoxLayout()
        edit_btn = QPushButton("Editar")
        edit_btn.clicked.connect(lambda: self.workspace and self.edit_requested.emit(self.workspace))
        del_btn = QPushButton("Remover")
        del_btn.clicked.connect(lambda: self.workspace and self.delete_requested.emit(self.workspace))
        meta.addStretch()
        meta.addWidget(edit_btn)
        meta.addWidget(del_btn)
        c.addLayout(meta)

        return w

    def show_empty(self) -> None:
        self.workspace = None
        self.setCurrentWidget(self._empty)

    def show_workspace(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._name.setText(workspace.name)

        self._desc.setText(workspace.description or "")
        self._desc.setVisible(bool(workspace.description))

        if workspace.folders:
            self._folders.setText("\n".join(f"• {f}" for f in workspace.folders))
        else:
            self._folders.setText("(sem pastas)")

        stacks = detect_stacks(workspace.folders)
        if stacks:
            labels = sorted(STACK_LABEL.get(s, s) for s in stacks)
            self._stacks.setText(f"Stack detectada: {', '.join(labels)}")
            self._stacks.setVisible(True)
        else:
            self._stacks.setVisible(False)

        self._rebuild_ide_buttons(stacks)
        self.setCurrentWidget(self._content)

    def _rebuild_ide_buttons(self, stacks: set[str]) -> None:
        while self._ide_row.count():
            item = self._ide_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        added: set[str] = set()
        for stack in sorted(stacks):
            ide_key = STACK_TO_IDE.get(stack)
            if not ide_key or ide_key in added:
                continue
            added.add(ide_key)
            btn = QPushButton(f"Abrir {IDE_LABEL[ide_key]}")
            btn.clicked.connect(lambda _, k=ide_key: self._launch_ide(k))
            self._ide_row.addWidget(btn)

        if "vscode" not in added:
            btn = QPushButton(f"Abrir {IDE_LABEL['vscode']}")
            btn.clicked.connect(lambda: self._launch_ide("vscode"))
            self._ide_row.addWidget(btn)

        self._ide_row.addStretch()

    def _launch_claude(self) -> None:
        if not self.workspace:
            return
        try:
            launch_claude(self.workspace, self.settings)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Falha ao abrir Claude", str(e))

    def _launch_konsole(self) -> None:
        if not self.workspace:
            return
        try:
            launch_konsole(self.workspace, self.settings)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Falha ao abrir terminal", str(e))

    def _launch_ide(self, ide_key: str) -> None:
        if not self.workspace:
            return
        try:
            launch_ide(ide_key, self.workspace, self.settings)
        except (LauncherError, FileNotFoundError) as e:
            QMessageBox.warning(self, f"Falha ao abrir {IDE_LABEL.get(ide_key, ide_key)}", str(e))
