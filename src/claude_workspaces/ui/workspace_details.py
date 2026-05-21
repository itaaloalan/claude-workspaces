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
from ..session_marks import is_starred
from ..settings import Settings
from ..stacks import STACK_LABEL, STACK_TO_IDE, detect_stacks
from .file_finder import FileFinder
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
    export_session_requested = Signal(ClaudeSession)
    columns_splitter_moved = Signal()
    open_file_requested = Signal(str)

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
        c.setContentsMargins(24, 18, 24, 14)
        c.setSpacing(12)

        # ---------- Header row: nome + status dot + badge + ações ⋯ ----------
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self._name = QLabel()
        self._name.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #f2f2f2;"
        )
        header_row.addWidget(self._name)

        # Status dot (verde = tem terminal rodando). Atualizado externamente.
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setStyleSheet(
            "background: #5ac35a; border-radius: 5px;"
        )
        self._status_dot.setVisible(False)
        header_row.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._active_badge = QLabel("Ativo")
        self._active_badge.setStyleSheet(
            "background: rgba(90, 195, 90, 38); color: #5ac35a; "
            "font-size: 10px; font-weight: 700; padding: 3px 10px; "
            "border-radius: 9px;"
        )
        self._active_badge.setVisible(False)
        header_row.addWidget(self._active_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        header_row.addStretch(1)

        # Botão ⋯ → menu (Editar / Remover) — substitui os botões soltos
        more_btn = QPushButton("⋯")
        more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        more_btn.setFixedSize(28, 28)
        more_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #c8c8c8; "
            "border: 0; border-radius: 4px; font-size: 16px; }"
            "QPushButton:hover { background: #2a2a2a; color: #fff; }"
        )
        more_btn.clicked.connect(self._show_workspace_actions_menu)
        self._more_btn = more_btn
        header_row.addWidget(more_btn)

        c.addLayout(header_row)

        # ---------- Chips row: Stack / Path / MCP ----------
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        self._stack_chip = self._make_chip("stack", "")
        self._path_chip = self._make_chip("folder", "")
        self._mcp_chip = self._make_chip("mcp", "")
        chips_row.addWidget(self._stack_chip)
        chips_row.addWidget(self._path_chip)
        chips_row.addWidget(self._mcp_chip)
        chips_row.addStretch(1)
        c.addLayout(chips_row)

        # Mantidos pra compatibilidade interna (usados em _refresh_mcp_status,
        # show_workspace). Ficam invisíveis — o conteúdo agora vai pros chips.
        self._stacks = QLabel(); self._stacks.setVisible(False)
        self._desc = QLabel(); self._desc.setVisible(False)
        self._folders = QLabel(); self._folders.setVisible(False)
        self._mcp_label = QLabel(); self._mcp_label.setVisible(False)
        self._mcp_edit_btn = QPushButton(); self._mcp_edit_btn.setVisible(False)
        self._mcp_remove_btn = QPushButton(); self._mcp_remove_btn.setVisible(False)
        self._mcp_edit_btn.clicked.connect(self._on_edit_mcp)
        self._mcp_remove_btn.clicked.connect(self._on_remove_mcp)

        # ---------- 4 botões grandes ----------
        big_row = QHBoxLayout()
        big_row.setSpacing(8)
        self._claude_btn = self._make_big_button("claude", "Abrir Claude", primary=True)
        self._claude_btn.clicked.connect(self._on_launch_claude)
        big_row.addWidget(self._claude_btn, stretch=1)

        self._shell_btn = self._make_big_button("terminal", "Abrir Terminal")
        self._shell_btn.clicked.connect(self._on_launch_shell)
        big_row.addWidget(self._shell_btn, stretch=1)

        # Botões de IDE detectados (PyCharm/IntelliJ/...) + VS Code default.
        # Cada um vira big_button, alinhado com o mockup.
        self._ide_row_host = QWidget()
        self._ide_row = QHBoxLayout(self._ide_row_host)
        self._ide_row.setContentsMargins(0, 0, 0, 0)
        self._ide_row.setSpacing(8)
        big_row.addWidget(self._ide_row_host, stretch=2)

        c.addLayout(big_row)

        # Git mora no dock direito da MainWindow; aqui fica só a coluna
        # de Sessões. O widget de Git é criado mesmo assim — MainWindow
        # puxa via accessor pra colocá-lo no dock.
        self._git_panel = GitPanel()
        self._git_panel.open_file_requested.connect(self.open_file_requested.emit)

        # Localizar arquivo moveu pra sidebar (esquerda) e abre num modal —
        # ver `MainWindow._open_file_finder_dialog`. Mantemos só uma
        # instância "shadow" pra preservar atributo/API antiga sem ocupar
        # espaço no painel de detalhes.
        self._file_finder = FileFinder()
        self._file_finder.open_file_requested.connect(self.open_file_requested.emit)
        self._file_finder.setVisible(False)

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
            self._set_chip(self._mcp_chip, f"MCP: nenhum servidor pra '{name}'")
            self._mcp_label.setText("")
            return
        if not is_postgres_mcp(name):
            self._set_chip(self._mcp_chip, f"MCP: {name} (não postgres)")
            return
        url = get_postgres_url(name) or ""
        self._set_chip(self._mcp_chip, f"MCP: {name} → {mask_password(url)}")

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

    def _make_chip(self, icon_key: str, text: str) -> QWidget:
        """Chip estilo pill com ícone SVG (qtawesome) + texto. Usado pra
        Stack, Path e MCP no cabeçalho do workspace.

        Retorna um QWidget container (não QLabel) pra poder embutir um
        QLabel-ícone + QLabel-texto lado a lado.
        """
        from PySide6.QtCore import QSize

        from .icons import ICONS, ic
        host = QWidget()
        host.setStyleSheet(
            "QWidget { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 12px; }"
        )
        h = QHBoxLayout(host)
        h.setContentsMargins(10, 3, 12, 3)
        h.setSpacing(6)

        icon_lbl = QLabel()
        qta_name = ICONS.get(icon_key, "")
        if qta_name:
            pix = ic(qta_name, color="#9aa0a6").pixmap(QSize(12, 12))
            icon_lbl.setPixmap(pix)
        h.addWidget(icon_lbl)

        text_lbl = QLabel(text)
        text_lbl.setStyleSheet(
            "QLabel { background: transparent; border: 0; color: #c8c8c8; "
            "font-size: 11px; }"
        )
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(text_lbl)

        # Refs pra o _set_chip atualizar depois
        host.setProperty("_text_lbl", text_lbl)
        return host

    def _set_chip(self, chip: QWidget, text: str, *, visible: bool = True) -> None:
        text_lbl = chip.property("_text_lbl")
        if isinstance(text_lbl, QLabel):
            text_lbl.setText(text)
        chip.setVisible(visible)

    def _make_big_button(
        self, icon: str, label: str, *, primary: bool = False
    ) -> QPushButton:
        """Botão grande estilo card pros 4 launchers do header.

        `icon` é uma chave do dicionário `icons.ICONS` (ex.: 'claude',
        'terminal', 'vscode') ou o nome qtawesome direto (ex.: 'fa5s.play').
        """
        from PySide6.QtCore import QSize

        from .icons import ICONS, ic
        btn = QPushButton(f"  {label}")
        # Resolve icon: aceita chave do nosso catálogo ou nome qta direto.
        qta_name = ICONS.get(icon, icon) if icon else None
        if qta_name:
            color = "#ffffff" if primary else "#e6e6e6"
            btn.setIcon(ic(qta_name, color=color))
            btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(32)
        if primary:
            btn.setStyleSheet(
                "QPushButton { background: #3d6ea8; color: #fff; border: 0; "
                "border-radius: 6px; padding: 5px 14px; font-size: 12px; "
                "font-weight: 600; text-align: center; }"
                "QPushButton:hover { background: #4a82c5; }"
                "QPushButton:pressed { background: #325a8c; }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background: #1f1f1f; color: #e6e6e6; "
                "border: 1px solid #2c2c2c; border-radius: 6px; "
                "padding: 5px 14px; font-size: 12px; text-align: center; }"
                "QPushButton:hover { border-color: #3d6ea8; color: #fff; }"
                "QPushButton:pressed { background: #181818; }"
            )
        return btn

    def _show_workspace_actions_menu(self) -> None:
        """Menu do botão ⋯ no header: Editar / Configurar MCP / Remover."""
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu
        if self.workspace is None:
            return
        menu = QMenu(self)
        edit_act = QAction("✏ Editar workspace", menu)
        edit_act.triggered.connect(
            lambda: self.edit_requested.emit(self.workspace)
        )
        menu.addAction(edit_act)
        mcp_act = QAction("🔌 Configurar MCP…", menu)
        mcp_act.triggered.connect(self._on_edit_mcp)
        menu.addAction(mcp_act)
        if mcp_exists(self.workspace.name):
            mcp_rm_act = QAction("🗑 Remover MCP", menu)
            mcp_rm_act.triggered.connect(self._on_remove_mcp)
            menu.addAction(mcp_rm_act)
        menu.addSeparator()
        del_act = QAction("✖ Remover workspace", menu)
        del_act.triggered.connect(
            lambda: self.delete_requested.emit(self.workspace)
        )
        menu.addAction(del_act)
        menu.exec_(self._more_btn.mapToGlobal(self._more_btn.rect().bottomRight()))

    def set_active_status(self, active: bool) -> None:
        """Atualiza o dot verde + badge 'Ativo' no header. Chamado pela
        MainWindow quando muda o running count do workspace atual."""
        self._status_dot.setVisible(active)
        self._active_badge.setVisible(active)

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
        # Chevron clicável pra colapsar/expandir a lista de sessões.
        # Estado persiste por sessão da app (não por workspace).
        self._sessions_collapsed = False
        self._sessions_toggle_btn = QPushButton("▾")
        self._sessions_toggle_btn.setFixedWidth(20)
        self._sessions_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_toggle_btn.setToolTip("Colapsar/expandir lista de sessões")
        self._sessions_toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; color: #888;"
            " font-size: 12px; padding: 0; }"
            "QPushButton:hover { color: #6aa9e0; }"
        )
        self._sessions_toggle_btn.clicked.connect(self._toggle_sessions_collapsed)
        header.addWidget(self._sessions_toggle_btn)
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

        self._only_starred_btn = QPushButton("★")
        self._only_starred_btn.setCheckable(True)
        self._only_starred_btn.setFixedWidth(28)
        self._only_starred_btn.setToolTip("Mostrar apenas sessões favoritadas")
        self._only_starred_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._only_starred_btn.setStyleSheet(
            "QPushButton { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; color: #888; font-size: 13px; padding: 2px; }"
            "QPushButton:hover { border-color: #3d6ea8; }"
            "QPushButton:checked { background: #3a2f10; border-color: #f0c040; color: #f0c040; }"
        )
        self._only_starred_btn.toggled.connect(self._apply_sessions_filter)
        header.addWidget(self._only_starred_btn)

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

    def _toggle_sessions_collapsed(self) -> None:
        self._sessions_collapsed = not self._sessions_collapsed
        collapsed = self._sessions_collapsed
        self._sessions_toggle_btn.setText("▸" if collapsed else "▾")
        # Esconde lista + filtro + botões juntos pra liberar espaço no
        # painel central; o header com o chevron continua visível pra
        # poder expandir de novo.
        self._sessions_list.setVisible(not collapsed)
        self._sessions_filter.setVisible(not collapsed)
        self._only_starred_btn.setVisible(not collapsed)

    def _apply_sessions_filter(self, *_args) -> None:
        needle = self._sessions_filter.text().strip().lower()
        only_starred = self._only_starred_btn.isChecked()
        for i in range(self._sessions_list.count()):
            item = self._sessions_list.item(i)
            session = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(session, ClaudeSession):
                hay = (session.preview or "").lower()
                hide = (bool(needle) and needle not in hay) or (
                    only_starred and not is_starred(session.id)
                )
                item.setHidden(hide)
            else:
                # Placeholder "nenhuma sessão" — esconde quando filtrando
                item.setHidden(bool(needle) or only_starred)

    # (git virou propriedade acessada via git_panel() pra reuso no dock direito)

    def show_empty(self) -> None:
        self.workspace = None
        self.setCurrentWidget(self._empty)

    def show_workspace(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._name.setText(workspace.name)

        # Chips: Stack | Path | MCP. Substitui os labels separados do
        # cabeçalho antigo (mantidos invisíveis pra compatibilidade interna).
        stacks = detect_stacks(workspace.folders)
        if stacks:
            labels = sorted(STACK_LABEL.get(s, s) for s in stacks)
            self._set_chip(self._stack_chip, f"Stack: {', '.join(labels)}")
        else:
            self._set_chip(self._stack_chip, "", visible=False)

        if workspace.folders:
            # Mostra só a primeira pasta no chip (paths longos viram tooltip)
            path_text = workspace.folders[0]
            if len(workspace.folders) > 1:
                path_text += f"  (+{len(workspace.folders) - 1})"
            self._set_chip(self._path_chip, path_text)
            self._path_chip.setToolTip("\n".join(workspace.folders))
        else:
            self._set_chip(self._path_chip, "", visible=False)

        self._rebuild_ide_buttons(stacks)
        self._file_finder.set_folders(workspace.folders)
        self._refresh_sessions()
        self._refresh_mcp_status()
        # git_panel.set_workspace é chamado pela MainWindow via
        # _broadcast_workspace (panel está em DOCK_PANEL_SPECS)

        self.setCurrentWidget(self._content)
        # Inicializa status (caller real é o MainWindow via set_active_status,
        # mas aqui evitamos flash de "Ativo" residual do workspace anterior)
        self.set_active_status(False)

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
            btn = self._make_big_button(ide_key, f"Abrir {IDE_LABEL[ide_key]}")
            btn.clicked.connect(lambda _, k=ide_key: self._launch_ide(k))
            self._ide_row.addWidget(btn, stretch=1)

        if "vscode" not in added:
            btn = self._make_big_button("vscode", f"Abrir {IDE_LABEL['vscode']}")
            btn.clicked.connect(lambda: self._launch_ide("vscode"))
            self._ide_row.addWidget(btn, stretch=1)

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
            card.export_requested.connect(self.export_session_requested.emit)
            card.star_toggled.connect(self._on_star_toggled)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            item.setSizeHint(card.sizeHint())
            self._sessions_list.addItem(item)
            self._sessions_list.setItemWidget(item, card)
        self._apply_sessions_filter()

    def _on_handoff_card(self, session: ClaudeSession) -> None:
        if not self.workspace:
            return
        self.handoff_requested.emit(self.workspace, session)

    def _on_star_toggled(self, _session: ClaudeSession, _starred: bool) -> None:
        # O filtro "só favoritas" precisa reagir quando uma sessão deixa de
        # ser favorita (some) ou volta a ser (aparece). Reaplica o filtro
        # — não precisa recarregar a lista do disco.
        self._apply_sessions_filter()

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
