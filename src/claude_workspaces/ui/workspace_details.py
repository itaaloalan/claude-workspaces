import logging
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from ..models import Workspace
from ..settings import Settings
from ..stacks import STACK_LABEL, STACK_TO_IDE, detect_stacks
from .git_panel import GitPanel
from .mcp_dialog import MCPDialog
from .session_card import SessionCard

log = logging.getLogger(__name__)


class WorkspaceDetailsPanel(QStackedWidget):
    edit_requested = Signal(Workspace)
    delete_requested = Signal(Workspace)
    launch_claude_requested = Signal(Workspace, str, str)  # workspace, resume_id, cwd_override
    launch_shell_requested = Signal(Workspace)
    handoff_requested = Signal(Workspace, ClaudeSession)
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
        msg.setStyleSheet("color: #b0b0b0;")
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
        self._stacks.setStyleSheet("color: #b0b0b0;")
        c.addWidget(self._stacks)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color: #d0d0d0;")
        c.addWidget(self._desc)

        self._folders = QLabel()
        self._folders.setWordWrap(True)
        self._folders.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._folders.setStyleSheet("color: #b0b0b0; font-family: monospace; font-size: 11px;")
        c.addWidget(self._folders)

        self._usage_label = QLabel()
        self._usage_label.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self._usage_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        c.addWidget(self._usage_label)

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

        # Git mora no dock direito da MainWindow; aqui fica só a coluna
        # de Sessões. O widget de Git é criado mesmo assim — MainWindow
        # puxa via accessor pra colocá-lo no dock.
        self._git_panel = GitPanel()
        self._git_panel.open_file_requested.connect(self.open_file_requested.emit)

        sessions = self._build_sessions_column()
        c.addWidget(sessions, stretch=1)

        # Splitter "fantasma" só pra preservar a API existente
        # (columns_sizes / restore_columns_sizes) sem quebrar callsites
        self._columns_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._columns_splitter.setVisible(False)

        scroll.setWidget(w)
        return scroll

    def git_panel(self) -> "GitPanel":
        return self._git_panel

    def _build_mcp_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self._mcp_label = QLabel()
        self._mcp_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._mcp_label.setStyleSheet("color: #c8c8c8; font-size: 11px;")
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
        self._sessions_filter = QLineEdit()
        self._sessions_filter.setPlaceholderText("Filtrar sessões…")
        self._sessions_filter.setClearButtonEnabled(True)
        self._sessions_filter.setMaximumWidth(220)
        self._sessions_filter.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 3px 8px; color: #e6e6e6; font-size: 11px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._sessions_filter.textChanged.connect(self._apply_sessions_filter)
        header.addWidget(self._sessions_filter, stretch=1)
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

    def _apply_sessions_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._sessions_list.count()):
            item = self._sessions_list.item(i)
            session = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(session, ClaudeSession):
                hay = (session.preview or "").lower()
                item.setHidden(bool(needle) and needle not in hay)
            else:
                # Placeholder "nenhuma sessão" — esconde quando filtrando
                item.setHidden(bool(needle))

    # (git virou propriedade acessada via git_panel() pra reuso no dock direito)

    def show_empty(self) -> None:
        self.workspace = None
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
        self._refresh_usage()
        # git_panel.set_workspace é chamado pela MainWindow via
        # _broadcast_workspace (panel está em DOCK_PANEL_SPECS)

        self.setCurrentWidget(self._content)

    def _refresh_usage(self) -> None:
        if not self.workspace or not self.workspace.folders:
            self._usage_label.setVisible(False)
            return
        try:
            from datetime import datetime, timedelta

            from ..usage_telemetry import (
                aggregate_usage_by_workspace,
                format_tokens,
            )
            since = datetime.now(UTC) - timedelta(days=30)
            all_usage = aggregate_usage_by_workspace(since=since)
        except Exception:
            log.debug("usage telemetry falhou no workspace %s",
                      getattr(self.workspace, "id", "?"), exc_info=True)
            self._usage_label.setVisible(False)
            return
        total_in = 0
        total_out = 0
        total_cache = 0
        total_cost = 0.0
        for folder in self.workspace.folders:
            stats = all_usage.get(folder)
            if not stats:
                continue
            total_in += stats.input_tokens
            total_out += stats.output_tokens
            total_cache += stats.cache_creation_tokens + stats.cache_read_tokens
            total_cost += stats.cost_usd
        if total_in + total_out + total_cache <= 0:
            self._usage_label.setVisible(False)
            return
        parts = [
            "<b>Uso (30d):</b>",
            f"in {format_tokens(total_in)}",
            f"out {format_tokens(total_out)}",
            f"cache {format_tokens(total_cache)}",
        ]
        if total_cost > 0:
            parts.append(f"≈ US$ {total_cost:.2f}")
        self._usage_label.setText("  ·  ".join(parts))
        self._usage_label.setVisible(True)

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
            card.delete_requested.connect(self._on_delete_session)
            card.handoff_requested.connect(self._on_handoff_card)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self._sessions_list.addItem(item)
            self._sessions_list.setItemWidget(item, card)

    def _on_handoff_card(self, session: ClaudeSession) -> None:
        if not self.workspace:
            return
        self.handoff_requested.emit(self.workspace, session)

    def refresh_sessions_soon(self) -> None:
        """Reescaneia a lista de sessões — chamada externamente quando um
        novo Claude é lançado (a sessão JSONL leva ~1-3s pra aparecer)."""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2500, self._refresh_sessions)
        QTimer.singleShot(6000, self._refresh_sessions)

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

    def _on_delete_session(self, session: ClaudeSession) -> None:
        when = datetime.fromtimestamp(session.mtime).strftime("%d/%m %H:%M")
        preview = (session.preview or "(sem prompt registrado)").replace("\n", " ").strip()
        if len(preview) > 80:
            preview = preview[:79] + "…"
        reply = QMessageBox.question(
            self,
            "Remover sessão",
            f"Excluir definitivamente esta sessão?\n\n"
            f"{when} — {preview}\n\n"
            f"Arquivo: {session.path}\n\nEssa ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            session.path.unlink(missing_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Falha ao remover sessão", str(e))
            return
        self._refresh_sessions()

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
