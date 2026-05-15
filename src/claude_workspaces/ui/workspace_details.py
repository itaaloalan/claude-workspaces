import logging

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
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

from ..claude_sessions import ClaudeSession, list_sessions_for_paths
from ..launchers import IDE_LABEL, LauncherError, launch_ide
from ..mcp_manager import delete_mcp, get_postgres_url, is_postgres_mcp, mask_password, mcp_exists
from ..models import Task, Workspace
from .git_panel import GitPanel, open_path_in_editor
from .mcp_dialog import MCPDialog
from ..settings import Settings
from ..stacks import STACK_LABEL, STACK_TO_IDE, detect_stacks
from .session_card import SessionCard
from .tasks_panel import TasksPanel


log = logging.getLogger(__name__)


class WorkspaceDetailsPanel(QStackedWidget):
    edit_requested = Signal(Workspace)
    delete_requested = Signal(Workspace)
    launch_claude_requested = Signal(Workspace, str, str)  # workspace, resume_id, cwd_override
    launch_shell_requested = Signal(Workspace)
    tasks_changed = Signal(Workspace)
    columns_splitter_moved = Signal()
    open_file_requested = Signal(str)  # caminho absoluto pra abrir no editor

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        w = QWidget()
        c = QVBoxLayout(w)
        c.setContentsMargins(20, 16, 20, 12)
        c.setSpacing(10)

        # Cabeçalho
        self._name = QLabel()
        self._name.setStyleSheet("font-size: 22px; font-weight: 700; color: #e6e6e6;")
        c.addWidget(self._name)

        self._stacks = QLabel()
        self._stacks.setStyleSheet("color: #888;")
        c.addWidget(self._stacks)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color: #bbb;")
        c.addWidget(self._desc)

        self._folders = QLabel()
        self._folders.setWordWrap(True)
        self._folders.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._folders.setStyleSheet("color: #888; font-family: monospace; font-size: 11px;")
        c.addWidget(self._folders)

        c.addLayout(self._build_mcp_row())

        # Linha única de ações principais
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        self._claude_btn = self._make_action_button("Abrir Claude", primary=True)
        self._claude_btn.clicked.connect(self._on_launch_claude)
        actions_row.addWidget(self._claude_btn)

        self._shell_btn = self._make_action_button("Abrir Terminal")
        self._shell_btn.clicked.connect(self._on_launch_shell)
        actions_row.addWidget(self._shell_btn)

        self._ide_row_host = QWidget()
        self._ide_row = QHBoxLayout(self._ide_row_host)
        self._ide_row.setContentsMargins(0, 0, 0, 0)
        self._ide_row.setSpacing(6)
        actions_row.addWidget(self._ide_row_host)

        actions_row.addStretch()

        edit_btn = self._make_action_button("Editar")
        edit_btn.clicked.connect(
            lambda: self.workspace and self.edit_requested.emit(self.workspace)
        )
        actions_row.addWidget(edit_btn)
        del_btn = self._make_action_button("Remover")
        del_btn.clicked.connect(
            lambda: self.workspace and self.delete_requested.emit(self.workspace)
        )
        actions_row.addWidget(del_btn)

        c.addLayout(actions_row)

        # Duas colunas: Sessões | Tarefas
        columns = QSplitter(Qt.Orientation.Horizontal)
        columns.setChildrenCollapsible(False)
        columns.setHandleWidth(8)
        self._columns_splitter = columns

        columns.addWidget(self._build_sessions_column())
        columns.addWidget(self._build_tasks_column())
        columns.addWidget(self._build_git_column())
        columns.setStretchFactor(0, 2)
        columns.setStretchFactor(1, 2)
        columns.setStretchFactor(2, 2)
        columns.setSizes([400, 300, 300])
        columns.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )
        columns.splitterMoved.connect(lambda *_: self.columns_splitter_moved.emit())
        c.addWidget(columns, stretch=1)

        scroll.setWidget(w)
        return scroll

    def _build_mcp_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self._mcp_label = QLabel()
        self._mcp_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._mcp_label.setStyleSheet("color: #aaa; font-size: 11px;")
        row.addWidget(self._mcp_label, stretch=1)

        self._mcp_edit_btn = QPushButton("Configurar MCP")
        self._mcp_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mcp_edit_btn.setStyleSheet(
            "QPushButton { background: #1f1f1f; color: #e6e6e6;"
            "  border: 1px solid #2c2c2c; border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
            "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
        )
        self._mcp_edit_btn.clicked.connect(self._on_edit_mcp)
        row.addWidget(self._mcp_edit_btn)

        self._mcp_remove_btn = QPushButton("Remover")
        self._mcp_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mcp_remove_btn.setStyleSheet(self._mcp_edit_btn.styleSheet())
        self._mcp_remove_btn.clicked.connect(self._on_remove_mcp)
        row.addWidget(self._mcp_remove_btn)

        return row

    def _refresh_mcp_status(self) -> None:
        if not self.workspace:
            return
        name = self.workspace.name
        if not mcp_exists(name):
            self._mcp_label.setText(
                f"<b>MCP:</b> nenhum servidor configurado pro nome "
                f"<code>{name}</code>"
            )
            self._mcp_edit_btn.setText("Criar MCP")
            self._mcp_remove_btn.setVisible(False)
            return
        if not is_postgres_mcp(name):
            self._mcp_label.setText(
                f"<b>MCP:</b> existe <code>{name}</code> mas não é postgres "
                f"(não dá pra editar daqui)"
            )
            self._mcp_edit_btn.setEnabled(False)
            self._mcp_remove_btn.setVisible(True)
            return
        url = get_postgres_url(name) or ""
        self._mcp_label.setText(
            f"<b>MCP:</b> <code>{name}</code> → {mask_password(url)}"
        )
        self._mcp_edit_btn.setEnabled(True)
        self._mcp_edit_btn.setText("Editar MCP")
        self._mcp_remove_btn.setVisible(True)

    def _on_edit_mcp(self) -> None:
        if not self.workspace:
            return
        name = self.workspace.name
        if is_postgres_mcp(name):
            current = get_postgres_url(name) or ""
        else:
            current = ""
        dialog = MCPDialog(name, current_url=current, parent=self)
        if dialog.exec():
            self._refresh_mcp_status()

    def _on_remove_mcp(self) -> None:
        if not self.workspace:
            return
        name = self.workspace.name
        reply = QMessageBox.question(
            self,
            "Remover MCP",
            f"Remover o MCP '{name}' do Claude Code? Workspaces que "
            f"dependem dele perdem acesso ao banco até reconfigurar.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_mcp(name)
        except OSError as e:
            QMessageBox.critical(self, "Falha ao remover", str(e))
            return
        self._refresh_mcp_status()

    def _make_action_button(self, label: str, primary: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setStyleSheet(
                "QPushButton { background: #3d6ea8; color: #fff; border: 0; "
                "border-radius: 6px; padding: 6px 12px; font-weight: 600; }"
                "QPushButton:hover { background: #4a82c5; }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background: #1f1f1f; color: #e6e6e6; "
                "border: 1px solid #2c2c2c; border-radius: 6px; padding: 6px 12px; }"
                "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
            )
        return btn

    def _build_sessions_column(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Sessões recentes do Claude</b>"))
        header.addStretch()
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Atualizar lista")
        refresh_btn.clicked.connect(self._refresh_sessions)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        # Cards ficam num QListWidget com setItemWidget — herda scroll
        # e seleção de graça
        self._sessions_list = QListWidget()
        self._sessions_list.setSpacing(4)
        self._sessions_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._sessions_list.setStyleSheet(
            "QListWidget { background: transparent; border: 0; }"
            "QListWidget::item { padding: 0; border: 0; }"
        )
        layout.addWidget(self._sessions_list, stretch=1)
        return col

    def _build_tasks_column(self) -> QWidget:
        self._tasks_panel = TasksPanel()
        self._tasks_panel.tasks_changed.connect(self.tasks_changed.emit)
        return self._tasks_panel

    def _build_git_column(self) -> QWidget:
        self._git_panel = GitPanel()
        self._git_panel.open_file_requested.connect(self.open_file_requested.emit)
        return self._git_panel

    def show_empty(self) -> None:
        self.workspace = None
        self._tasks_panel.set_workspace(None)
        self.setCurrentWidget(self._empty)

    def show_workspace(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._name.setText(workspace.name)
        self._desc.setText(workspace.description or "")
        self._desc.setVisible(bool(workspace.description))

        if workspace.folders:
            self._folders.setText(" · ".join(workspace.folders))
            self._folders.setVisible(True)
        else:
            self._folders.setVisible(False)

        stacks = detect_stacks(workspace.folders)
        if stacks:
            labels = sorted(STACK_LABEL.get(s, s) for s in stacks)
            self._stacks.setText(f"Stack: {', '.join(labels)}")
            self._stacks.setVisible(True)
        else:
            self._stacks.setVisible(False)

        self._rebuild_ide_buttons(stacks)
        self._refresh_sessions()
        self._refresh_mcp_status()
        self._tasks_panel.set_workspace(workspace)
        self._git_panel.set_workspace(workspace)

        self.setCurrentWidget(self._content)

    def restore_columns_sizes(self, sizes: list[int]) -> None:
        if sizes and len(sizes) == self._columns_splitter.count():
            self._columns_splitter.setSizes(sizes)

    def columns_sizes(self) -> list[int]:
        return list(self._columns_splitter.sizes())

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
            btn = self._make_action_button(f"Abrir {IDE_LABEL[ide_key]}")
            btn.clicked.connect(lambda _, k=ide_key: self._launch_ide(k))
            self._ide_row.addWidget(btn)

        if "vscode" not in added:
            btn = self._make_action_button(f"Abrir {IDE_LABEL['vscode']}")
            btn.clicked.connect(lambda: self._launch_ide("vscode"))
            self._ide_row.addWidget(btn)

    def _refresh_sessions(self) -> None:
        self._sessions_list.clear()
        if not self.workspace or not self.workspace.folders:
            return
        cwd, _ = self.workspace.launch_paths()
        candidate_paths = list({cwd, *self.workspace.folders})
        sessions = list_sessions_for_paths(candidate_paths, limit=20)
        if not sessions:
            placeholder = QListWidgetItem("(nenhuma sessão encontrada para esse projeto)")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._sessions_list.addItem(placeholder)
            return
        show_origin = len(self.workspace.folders) > 1
        for s in sessions:
            card = SessionCard(s, show_origin=show_origin)
            card.resume_requested.connect(self._on_resume_card)
            card.convert_to_task_requested.connect(self._on_convert_to_task)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self._sessions_list.addItem(item)
            self._sessions_list.setItemWidget(item, card)

    def _on_launch_claude(self) -> None:
        if not self.workspace or not self.workspace.folders:
            QMessageBox.warning(self, "Workspace sem pastas", "Adicione pelo menos uma pasta.")
            return
        self.launch_claude_requested.emit(self.workspace, "", "")

    def _on_launch_shell(self) -> None:
        if not self.workspace or not self.workspace.folders:
            return
        self.launch_shell_requested.emit(self.workspace)

    def _on_resume_card(self, session) -> None:
        if not self.workspace:
            return
        self.launch_claude_requested.emit(self.workspace, session.id, session.origin_cwd)

    def _on_convert_to_task(self, session: ClaudeSession) -> None:
        if not self.workspace:
            return
        suggested = (session.preview or "").replace("\n", " ").strip()
        if not suggested:
            when = datetime.fromtimestamp(session.mtime)
            suggested = f"Continuar sessão de {when.strftime('%d/%m %H:%M')}"
        if len(suggested) > 200:
            suggested = suggested[:199] + "…"
        title, ok = QInputDialog.getText(
            self,
            "Nova tarefa a partir da sessão",
            "Título da tarefa:",
            text=suggested,
        )
        if not ok:
            return
        title = title.strip()
        if not title:
            return
        self.workspace.tasks.append(Task(title=title))
        self._tasks_panel.set_workspace(self.workspace)
        self.tasks_changed.emit(self.workspace)

    def _launch_ide(self, ide_key: str) -> None:
        if not self.workspace:
            return
        try:
            launch_ide(ide_key, self.workspace, self.settings)
        except (LauncherError, FileNotFoundError) as e:
            log.exception("Falha ao abrir %s (workspace=%s)", ide_key, self.workspace.name)
            QMessageBox.warning(
                self,
                f"Falha ao abrir {IDE_LABEL.get(ide_key, ide_key)}",
                str(e),
            )
