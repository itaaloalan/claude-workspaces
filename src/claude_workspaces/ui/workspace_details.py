import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..claude_sessions import ClaudeSession, list_sessions
from ..launchers import IDE_LABEL, LauncherError, launch_ide
from ..models import Workspace
from ..settings import Settings
from ..stacks import STACK_LABEL, STACK_TO_IDE, detect_stacks
from .terminal_area import TerminalArea


log = logging.getLogger(__name__)


class WorkspaceDetailsPanel(QStackedWidget):
    edit_requested = Signal(Workspace)
    delete_requested = Signal(Workspace)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.workspace: Workspace | None = None
        self._terminal_areas: dict[str, TerminalArea] = {}

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
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._build_top_section())
        splitter.addWidget(scroll)

        self._terminal_host = QStackedWidget()
        self._empty_terminal = QLabel(
            "(sem terminal aberto — clique em 'Abrir Claude' ou 'Abrir Terminal' acima)"
        )
        self._empty_terminal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_terminal.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 24px;"
        )
        self._terminal_host.addWidget(self._empty_terminal)
        splitter.addWidget(self._terminal_host)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 420])
        return splitter

    def _build_top_section(self) -> QWidget:
        w = QWidget()
        c = QVBoxLayout(w)
        c.setContentsMargins(20, 16, 20, 12)
        c.setSpacing(8)

        self._name = QLabel()
        self._name.setStyleSheet("font-size: 20px; font-weight: bold;")
        c.addWidget(self._name)

        self._stacks = QLabel()
        self._stacks.setStyleSheet("color: #888;")
        c.addWidget(self._stacks)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color: #bbb;")
        c.addWidget(self._desc)

        c.addWidget(QLabel("<b>Pastas</b>"))
        self._folders = QLabel()
        self._folders.setWordWrap(True)
        self._folders.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._folders.setStyleSheet("color: #aaa; font-family: monospace;")
        c.addWidget(self._folders)

        c.addWidget(QLabel("<b>Abrir com</b>"))
        primary_row = QHBoxLayout()
        claude_btn = QPushButton("Abrir Claude (nova aba)")
        claude_btn.clicked.connect(self._launch_claude_new)
        konsole_btn = QPushButton("Abrir Terminal (nova aba)")
        konsole_btn.clicked.connect(self._launch_shell)
        primary_row.addWidget(claude_btn)
        primary_row.addWidget(konsole_btn)
        primary_row.addStretch()
        c.addLayout(primary_row)

        self._ide_row_host = QWidget()
        self._ide_row = QHBoxLayout(self._ide_row_host)
        self._ide_row.setContentsMargins(0, 0, 0, 0)
        c.addWidget(self._ide_row_host)

        sess_header = QHBoxLayout()
        sess_header.addWidget(QLabel("<b>Sessões recentes do Claude</b>"))
        sess_header.addStretch()
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Atualizar lista")
        refresh_btn.clicked.connect(self._refresh_sessions)
        sess_header.addWidget(refresh_btn)
        c.addLayout(sess_header)

        self._sessions_list = QListWidget()
        self._sessions_list.setMaximumHeight(150)
        self._sessions_list.setStyleSheet("color: #ccc;")
        self._sessions_list.itemDoubleClicked.connect(self._resume_session_item)
        c.addWidget(self._sessions_list)

        sess_actions = QHBoxLayout()
        resume_btn = QPushButton("Retomar selecionada (nova aba)")
        resume_btn.clicked.connect(self._resume_selected_session)
        sess_actions.addWidget(resume_btn)
        sess_actions.addStretch()
        c.addLayout(sess_actions)

        meta = QHBoxLayout()
        edit_btn = QPushButton("Editar")
        edit_btn.clicked.connect(
            lambda: self.workspace and self.edit_requested.emit(self.workspace)
        )
        del_btn = QPushButton("Remover")
        del_btn.clicked.connect(
            lambda: self.workspace and self.delete_requested.emit(self.workspace)
        )
        meta.addStretch()
        meta.addWidget(edit_btn)
        meta.addWidget(del_btn)
        c.addLayout(meta)

        c.addStretch()
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
        self._refresh_sessions()

        if workspace.name in self._terminal_areas:
            self._terminal_host.setCurrentWidget(self._terminal_areas[workspace.name])
        else:
            self._terminal_host.setCurrentIndex(0)

        self.setCurrentWidget(self._content)

    def cleanup_workspace(self, name: str) -> None:
        area = self._terminal_areas.pop(name, None)
        if area is None:
            return
        area.close_all()
        self._terminal_host.removeWidget(area)
        area.deleteLater()

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

    def _refresh_sessions(self) -> None:
        self._sessions_list.clear()
        if not self.workspace or not self.workspace.folders:
            return
        cwd, _ = self.workspace.launch_paths()
        sessions = list_sessions(cwd, limit=15)
        if not sessions:
            placeholder = QListWidgetItem("(nenhuma sessão encontrada para esse projeto)")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._sessions_list.addItem(placeholder)
            return
        for s in sessions:
            item = QListWidgetItem(s.label())
            item.setData(Qt.ItemDataRole.UserRole, s)
            item.setToolTip(f"ID: {s.id}\n\n{s.preview}")
            self._sessions_list.addItem(item)

    def _get_terminal_area(self) -> TerminalArea | None:
        if not self.workspace:
            return None
        name = self.workspace.name
        if name not in self._terminal_areas:
            area = TerminalArea()
            self._terminal_areas[name] = area
            self._terminal_host.addWidget(area)
        return self._terminal_areas[name]

    def _launch_claude_new(self) -> None:
        self._launch_claude()

    def _launch_claude(self, *, resume_session_id: str | None = None) -> None:
        if not self.workspace or not self.workspace.folders:
            QMessageBox.warning(self, "Workspace sem pastas", "Adicione pelo menos uma pasta.")
            return
        cwd, extras = self.workspace.launch_paths()
        argv = [self.settings.claude_command, *self.settings.claude_extra_args]
        if resume_session_id:
            argv += ["--resume", resume_session_id]
        for extra in extras:
            argv += ["--add-dir", extra]

        area = self._get_terminal_area()
        if area is None:
            return
        self._terminal_host.setCurrentWidget(area)
        title = "claude (resume)" if resume_session_id else "claude"
        title = f"{title} #{area.count() + 1}"
        terminal = area.add_terminal(title)
        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=f"claude — {self.workspace.name}",
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir Claude embutido")
            QMessageBox.warning(self, "Falha", str(e))

    def _launch_shell(self) -> None:
        if not self.workspace or not self.workspace.folders:
            return
        cwd, _ = self.workspace.launch_paths()
        area = self._get_terminal_area()
        if area is None:
            return
        self._terminal_host.setCurrentWidget(area)
        terminal = area.add_terminal(f"shell #{area.count() + 1}")
        try:
            terminal.start_interactive_shell(
                cwd,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir shell embutido")
            QMessageBox.warning(self, "Falha", str(e))

    def _resume_session_item(self, item: QListWidgetItem) -> None:
        session = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(session, ClaudeSession):
            self._launch_claude(resume_session_id=session.id)

    def _resume_selected_session(self) -> None:
        item = self._sessions_list.currentItem()
        if item is None:
            return
        self._resume_session_item(item)

    def _launch_ide(self, ide_key: str) -> None:
        if not self.workspace:
            return
        try:
            launch_ide(ide_key, self.workspace, self.settings)
        except (LauncherError, FileNotFoundError) as e:
            log.exception(
                "Falha ao abrir %s (workspace=%s)", ide_key, self.workspace.name
            )
            QMessageBox.warning(
                self,
                f"Falha ao abrir {IDE_LABEL.get(ide_key, ide_key)}",
                str(e),
            )
