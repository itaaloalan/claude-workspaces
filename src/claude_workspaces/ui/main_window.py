import logging
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..claude_sessions import ClaudeSession, list_sessions_for_paths
from ..launchers import (
    LauncherError,
    find_app_repo_root,
    launch_claude_in_dir,
)
from ..models import Workspace
from ..settings import Settings
from .activity_bar import (
    VIEW_CATALOG,
    VIEW_HOOKS,
    VIEW_MCP,
    VIEW_PLUGINS,
    VIEW_SETTINGS,
    VIEW_WORKSPACES,
    ActivityBar,
)
from .coordinators import (
    DockCoordinator,
    LaunchCoordinator,
    TerminalCoordinator,
    WorkspaceCoordinator,
)
from .memory_panel import MemoryPanel
from .panels import DockPanelSpec
from .settings_panel import SettingsPanel
from .skills_panel import SkillsPanel
from .terminal_area import TerminalArea
from .terminal_child_widget import (
    STATE_DONE,
    STATE_IDLE,
    STATE_WORKING,
    TerminalChildWidget,
)
from .terminal_widget import TerminalWidget
from .top_bar import TopBar
from .views import CatalogView, HooksView, McpView, PluginsView
from .workspace_details import WorkspaceDetailsPanel
from .workspace_dialog import WorkspaceDialog

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claude Workspaces")

        self.settings = Settings.load()

        # ---------- Coordinators (composição) ----------
        self.workspaces_coord = WorkspaceCoordinator(self)
        self.terminals_coord = TerminalCoordinator(self)
        self.launch_coord = LaunchCoordinator(
            self.settings, self.terminals_coord, self
        )

        # Backward-compat: shadow attrs apontam pros coordinators
        self._terminal_placeholder_idx: int = 0
        self._sidebar_last_size: int = 260
        self._terminal_last_size: int = 520
        self._content_last_size: int = 380
        # Plugin host é inicializado depois do _build_ui — mas algumas callbacks
        # disparam antes disso. Pré-inicializa como None pra que checks `is not None`
        # funcionem sem AttributeError.
        self._plugin_host = None

        self._build_ui()

        # Signal wiring entre coordinators e UI
        self.workspaces_coord.workspaces_changed.connect(self.refresh_list)
        self.workspaces_coord.workspace_deleted.connect(self._cleanup_terminal_for)
        self.terminals_coord.workspace_running_changed.connect(self._on_workspace_running)
        self.terminals_coord.tab_activity_changed.connect(self._handle_tab_activity)
        self.terminals_coord.tab_removed.connect(self._handle_tab_removed)
        self.terminals_coord.inbox_changed.connect(self.top_bar.set_inbox_count)
        self.terminals_coord.spinner_tick.connect(self._on_spinner_tick)
        self.terminals_coord.terminal_area_created.connect(self._on_area_created)
        self.launch_coord.sessions_refresh_requested.connect(
            self.details.refresh_sessions_soon
        )

        self._restore_geometry()
        self.refresh_list()
        self._init_plugin_host()

    @property
    def workspaces(self) -> list[Workspace]:
        return self.workspaces_coord.workspaces

    # ---------- construção ----------

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.top_bar = TopBar()
        self.top_bar.search_changed.connect(self._apply_filter)
        self.top_bar.search_submitted.connect(self._search_submit)
        self.top_bar.settings_clicked.connect(self._show_settings)
        self.top_bar.home_clicked.connect(self._show_workspaces)
        self.top_bar.toggle_sidebar_clicked.connect(self._toggle_sidebar)
        self.top_bar.inbox_clicked.connect(self._show_inbox)
        outer.addWidget(self.top_bar)

        splitter_css = (
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
            "QSplitter::handle:pressed { background: #4a82c5; }"
        )

        # Splitter horizontal: sidebar full-height | painel direito
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setChildrenCollapsible(True)
        self.body_splitter.setHandleWidth(8)
        self.body_splitter.setStyleSheet(splitter_css)

        self._sidebar = self._build_sidebar()
        self._sidebar.setMinimumWidth(0)
        self.body_splitter.addWidget(self._sidebar)

        # Splitter vertical interno ao painel direito:
        # conteúdo (details / settings) em cima, terminal embaixo —
        # terminal nunca passa por baixo do sidebar
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        # collapsible=False → drag freeform sem snap-to-zero embaixo do
        # threshold (~15px). Toggle Ctrl+J / minimize button continuam
        # funcionando via setSizes([N, 0]) que ignora a constraint.
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.setHandleWidth(8)
        self.right_splitter.setStyleSheet(splitter_css)

        self.content_stack = QStackedWidget()
        self.details = WorkspaceDetailsPanel(self.settings)
        self.details.edit_requested.connect(self.edit_workspace)
        self.details.delete_requested.connect(self.delete_workspace)
        self.details.launch_claude_requested.connect(self._launch_claude_for)
        self.details.launch_shell_requested.connect(self._launch_shell_for)
        self.details.open_file_requested.connect(self._open_file_in_editor)
        self.details.handoff_requested.connect(self._handoff_session)
        self.details.export_session_requested.connect(self._export_session)
        self.content_stack.addWidget(self.details)

        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.set_workspace_getter(self._current_workspace)
        # Wrap em QScrollArea — SettingsPanel tem várias rows de form
        # e seu minimumSizeHint natural (~870px) trava o right_splitter
        # com collapsible=False, impedindo o terminal de crescer/maximizar.
        self._settings_scroll = QScrollArea()
        self._settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setWidget(self.settings_panel)
        self.content_stack.addWidget(self._settings_scroll)
        self.content_stack.setMinimumHeight(0)
        self.content_stack.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored
        )

        self.right_splitter.addWidget(self.content_stack)

        # Painel do terminal: barra de controle (maximizar/minimizar)
        # + stack de TerminalAreas por workspace
        self._terminal_pane = self._build_terminal_pane()
        self._terminal_pane.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored
        )
        self.right_splitter.addWidget(self._terminal_pane)

        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)
        if self.settings.right_splitter_sizes:
            sizes = list(self.settings.right_splitter_sizes)
            # Legacy: usuários antigos têm [sum, 0] (terminal escondido).
            # Promove pra "minimizado mas header visível"
            if len(sizes) >= 2 and sizes[1] <= 4:
                header_h = self._terminal_header_height()
                total = sum(sizes) or 800
                sizes = [max(total - header_h, 200), header_h]
                self.terminal_host.setVisible(False)
            self.right_splitter.setSizes(sizes)
        else:
            self.right_splitter.setSizes([380, 520])

        self.body_splitter.addWidget(self.right_splitter)

        # Dock direito (3ª coluna): Tarefas + Git + Skills colapsáveis
        self.right_dock = self._build_right_dock()
        self.right_dock.setMinimumWidth(0)
        self.body_splitter.addWidget(self.right_dock)

        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setStretchFactor(2, 0)
        sizes = self.settings.body_splitter_sizes
        if sizes and len(sizes) == 3:
            self.body_splitter.setSizes(sizes)
        else:
            self.body_splitter.setSizes([240, 760, 340])

        # ---------- Top-level shell: activity bar + main stack ----------
        # body_splitter (workspaces flow) é só uma das views do main_stack.
        # Catálogo / Hooks / MCP têm seus próprios widgets que ocupam o
        # mesmo espaço quando ativados pela activity bar.
        shell_row = QHBoxLayout()
        shell_row.setContentsMargins(0, 0, 0, 0)
        shell_row.setSpacing(0)

        self.activity_bar = ActivityBar()
        self.activity_bar.view_changed.connect(self._on_activity_view_changed)
        shell_row.addWidget(self.activity_bar)

        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.body_splitter)            # 0: workspaces+settings
        self.catalog_view = CatalogView(settings=self.settings)
        self.main_stack.addWidget(self.catalog_view)             # 1: catálogo
        self.hooks_view = HooksView()
        self.main_stack.addWidget(self.hooks_view)               # 2: hooks
        self.mcp_view = McpView()
        self.main_stack.addWidget(self.mcp_view)                 # 3: mcp
        self.plugins_view = PluginsView()
        self.main_stack.addWidget(self.plugins_view)             # 4: plugins
        shell_row.addWidget(self.main_stack, stretch=1)

        outer.addLayout(shell_row, stretch=1)
        self.setCentralWidget(central)

        # Restaurar tamanhos das colunas internas dos details
        if self.settings.workspace_columns_sizes:
            self.details.restore_columns_sizes(self.settings.workspace_columns_sizes)

        # Persistência ao vivo (debounced) — qualquer movimento dos
        # splitters dispara save após 600ms de inatividade
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(600)
        self._layout_save_timer.timeout.connect(self._persist_layout)

        self.body_splitter.splitterMoved.connect(self._schedule_layout_save)
        self.right_splitter.splitterMoved.connect(self._schedule_layout_save)
        self.details.columns_splitter_moved.connect(self._schedule_layout_save)

        self._install_shortcuts()
        # Estado inicial dos botões do terminal
        self.right_splitter.splitterMoved.connect(lambda *_: self._refresh_terminal_btns())
        QTimer.singleShot(0, self._refresh_terminal_btns)

    def _schedule_layout_save(self, *_args) -> None:
        self._layout_save_timer.start()

    def _persist_layout(self) -> None:
        try:
            self.settings.body_splitter_sizes = list(self.body_splitter.sizes())
            self.settings.right_splitter_sizes = list(self.right_splitter.sizes())
            self.settings.workspace_columns_sizes = self.details.columns_sizes()
            g = self.geometry()
            self.settings.window_geometry = [g.x(), g.y(), g.width(), g.height()]
            self.settings.save()
        except Exception:
            log.exception("Falha ao persistir layout ao vivo")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def _install_shortcuts(self) -> None:
        # Layout
        QShortcut(QKeySequence("Ctrl+B"), self, self._toggle_sidebar)
        QShortcut(QKeySequence("Ctrl+J"), self, self._toggle_terminal)
        QShortcut(QKeySequence("Ctrl+Shift+B"), self, self._toggle_right_dock)
        # Workspace
        QShortcut(QKeySequence("Ctrl+Return"), self, self._launch_current_claude)
        QShortcut(QKeySequence("Ctrl+,"), self, self._show_settings)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_workspace)
        for i in range(1, 10):
            QShortcut(
                QKeySequence(f"Ctrl+{i}"),
                self,
                lambda idx=i - 1: self._jump_to_workspace(idx),
            )
        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: self._cycle_workspace(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: self._cycle_workspace(-1))
        # Terminal
        QShortcut(QKeySequence("Ctrl+T"), self, self._new_terminal_tab)
        QShortcut(QKeySequence("Ctrl+Shift+W"), self, self._close_active_terminal_tab)
        QShortcut(QKeySequence("Ctrl+K"), self, self._clear_active_terminal)
        QShortcut(QKeySequence("Ctrl+Alt+Right"), self, lambda: self._cycle_terminal_tab(1))
        QShortcut(QKeySequence("Ctrl+Alt+Left"), self, lambda: self._cycle_terminal_tab(-1))
        # Arquivos
        QShortcut(QKeySequence("Ctrl+P"), self, self._quick_open_file)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_folder_in_file_manager)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_primary_folder)
        # Resume da última sessão do workspace atual
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, self._resume_last_session)
        # Busca em sessões
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self._show_sessions_search)
        # Views (activity bar) — Ctrl+Shift+1..4 (Ctrl+1..9 já é workspace jump)
        QShortcut(
            QKeySequence("Ctrl+Shift+1"), self,
            lambda: self.activity_bar.activate(VIEW_WORKSPACES),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+2"), self,
            lambda: self.activity_bar.activate(VIEW_CATALOG),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+3"), self,
            lambda: self.activity_bar.activate(VIEW_HOOKS),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+4"), self,
            lambda: self.activity_bar.activate(VIEW_MCP),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+5"), self,
            lambda: self.activity_bar.activate(VIEW_PLUGINS),
        )
        # Paleta de comandos de plugins
        QShortcut(QKeySequence("Ctrl+P"), self, self._open_plugin_palette)
        # Help
        QShortcut(QKeySequence("Ctrl+/"), self, self._show_shortcuts)
        QShortcut(QKeySequence("F1"), self, self._show_shortcuts)

    def _visible_rows(self) -> list[int]:
        return [
            i for i in range(self.list_widget.topLevelItemCount())
            if not self.list_widget.topLevelItem(i).isHidden()
        ]

    def _jump_to_workspace(self, index: int) -> None:
        rows = self._visible_rows()
        if 0 <= index < len(rows):
            self.list_widget.setCurrentItem(
                self.list_widget.topLevelItem(rows[index])
            )

    def _cycle_workspace(self, delta: int) -> None:
        rows = self._visible_rows()
        if not rows:
            return
        current_item = self.list_widget.currentItem()
        current = -1
        if current_item is not None:
            top = current_item if current_item.parent() is None else current_item.parent()
            current = self.list_widget.indexOfTopLevelItem(top)
        try:
            pos = rows.index(current)
        except ValueError:
            pos = 0
        next_pos = (pos + delta) % len(rows)
        self.list_widget.setCurrentItem(self.list_widget.topLevelItem(rows[next_pos]))

    def _toggle_sidebar(self) -> None:
        sizes = self.body_splitter.sizes()
        if not sizes:
            return
        if sizes[0] > 0:
            self._sidebar_last_size = sizes[0]
            self.body_splitter.setSizes([0, sum(sizes)])
        else:
            target = self._sidebar_last_size or 260
            self.body_splitter.setSizes([target, max(sum(sizes) - target, 200)])
        self._schedule_layout_save()

    def _terminal_header_height(self) -> int:
        """Altura do header do terminal — usado como 'min height' quando
        minimizado (barra fica visível e clicável pra restaurar)."""
        if hasattr(self, "_terminal_header"):
            return max(self._terminal_header.sizeHint().height(), 28)
        return 32

    def _terminal_is_minimized(self) -> bool:
        sizes = self.right_splitter.sizes()
        if not sizes or len(sizes) < 2:
            return False
        return sizes[1] <= self._terminal_header_height() + 4

    def _toggle_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        if not sizes or len(sizes) < 2:
            return
        header_h = self._terminal_header_height()
        if not self._terminal_is_minimized():
            # Minimizar: terminal_host some, mas o header continua
            # visível (clicável pra restaurar)
            self._terminal_last_size = sizes[1]
            self.terminal_host.setVisible(False)
            self.right_splitter.setSizes(
                [max(sum(sizes) - header_h, 200), header_h]
            )
        else:
            target = self._terminal_last_size or 420
            self.terminal_host.setVisible(True)
            self.right_splitter.setSizes(
                [max(sum(sizes) - target, 200), target]
            )
        self._refresh_terminal_btns()
        self._schedule_layout_save()

    def _maximize_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        total = sum(sizes) or 800
        if sizes[0] > 0:
            self._content_last_size = sizes[0]
        self.terminal_host.setVisible(True)
        self.right_splitter.setSizes([0, total])
        self._refresh_terminal_btns()
        self._schedule_layout_save()

    def _restore_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        total = sum(sizes) or 800
        self.terminal_host.setVisible(True)
        # 50/50 — equilíbrio razoável após maximizar ou minimizar
        half = total // 2
        self.right_splitter.setSizes([total - half, half])
        self._refresh_terminal_btns()
        self._schedule_layout_save()

    def _refresh_terminal_btns(self) -> None:
        sizes = self.right_splitter.sizes()
        if not sizes or len(sizes) < 2:
            return
        content_visible = sizes[0] > 0
        minimized = self._terminal_is_minimized()
        self._term_max_btn.setEnabled(content_visible)
        self._term_min_btn.setEnabled(not minimized)
        # Restaurar só faz sentido se algum lado está colapsado
        terminal_full = not minimized
        self._term_restore_btn.setEnabled(not (content_visible and terminal_full))

    def _launch_current_claude(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        ws = current.data(Qt.ItemDataRole.UserRole)
        self._launch_claude_for(ws, "", "")

    def _toggle_right_dock(self) -> None:
        sizes = self.body_splitter.sizes()
        if not sizes or len(sizes) < 3:
            return
        if sizes[2] > 0:
            self._right_dock_last_size = sizes[2]
            self.body_splitter.setSizes([sizes[0], sizes[1] + sizes[2], 0])
        else:
            target = getattr(self, "_right_dock_last_size", 340) or 340
            self.body_splitter.setSizes(
                [sizes[0], max(sizes[1] - target, 200), target]
            )
        self._schedule_layout_save()

    def _current_workspace(self) -> Workspace | None:
        current = self.list_widget.currentItem()
        if current is None:
            return None
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Workspace):
            return data
        # Pode ser um filho (ClaudeSession) — sobe pro parent
        parent = current.parent()
        if parent is not None:
            data = parent.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Workspace):
                return data
        return None

    def _on_activity_view_changed(self, view_id: str) -> None:
        """Activity bar trocou a view top-level. Carrega lazy."""
        if view_id == VIEW_WORKSPACES:
            self.main_stack.setCurrentWidget(self.body_splitter)
            self.content_stack.setCurrentIndex(0)
        elif view_id == VIEW_SETTINGS:
            self.main_stack.setCurrentWidget(self.body_splitter)
            self.content_stack.setCurrentWidget(self._settings_scroll)
        elif view_id == VIEW_CATALOG:
            self.main_stack.setCurrentWidget(self.catalog_view)
            self.catalog_view.set_workspace(self._current_workspace())
        elif view_id == VIEW_HOOKS:
            self.main_stack.setCurrentWidget(self.hooks_view)
            self.hooks_view.set_workspace(self._current_workspace())
        elif view_id == VIEW_MCP:
            self.main_stack.setCurrentWidget(self.mcp_view)
            self.mcp_view.set_workspace(self._current_workspace())
        elif view_id == VIEW_PLUGINS:
            self.main_stack.setCurrentWidget(self.plugins_view)
            self.plugins_view.refresh()

    def _new_terminal_tab(self) -> None:
        ws = self._current_workspace()
        if ws and ws.folders:
            self._launch_shell_for(ws)

    def _active_terminal_area(self) -> TerminalArea | None:
        w = self.terminal_host.currentWidget()
        return w if isinstance(w, TerminalArea) else None

    def _close_active_terminal_tab(self) -> None:
        area = self._active_terminal_area()
        if area is None or area.count() == 0:
            return
        area._close_tab(area.tabs.currentIndex())

    def _clear_active_terminal(self) -> None:
        area = self._active_terminal_area()
        if area is None or area.count() == 0:
            return
        widget = area.tabs.currentWidget()
        # Manda Ctrl+L (form-feed) pra limpar — funciona em bash/zsh/fish/claude
        if isinstance(widget, TerminalWidget) and widget.session.is_running():
            widget.session.write(b"\x0c")

    def _cycle_terminal_tab(self, delta: int) -> None:
        area = self._active_terminal_area()
        if area is None or area.count() == 0:
            return
        idx = (area.tabs.currentIndex() + delta) % area.count()
        area.tabs.setCurrentIndex(idx)

    def _quick_open_file(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from ..services.quick_open import find_files
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        pattern, ok = QInputDialog.getText(
            self,
            "Quick open",
            f"Nome (ou parte) do arquivo em {Path(ws.folders[0]).name}:",
        )
        if not ok or not pattern.strip():
            return
        matches = find_files(ws.folders, pattern.strip())
        if not matches:
            QMessageBox.information(
                self, "Quick open", f"Nenhum arquivo casa com '{pattern}'"
            )
            return
        choice, ok = QInputDialog.getItem(
            self, "Quick open", f"{len(matches)} match(es):",
            matches, 0, False,
        )
        if ok and choice:
            self._open_file_in_editor(choice)

    def _open_folder_in_file_manager(self) -> None:
        from ..errors import LaunchError
        from ..services.system_open import open_in_file_manager
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        try:
            open_in_file_manager(ws.folders[0])
        except LaunchError as e:
            QMessageBox.warning(self, "Falha ao abrir pasta", str(e))

    def _copy_primary_folder(self) -> None:
        from PySide6.QtGui import QGuiApplication
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        QGuiApplication.clipboard().setText(ws.folders[0])

    def _show_shortcuts(self) -> None:
        from .shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _resume_last_session(self) -> None:
        """Ctrl+Shift+R: retoma a sessão Claude mais recente do workspace
        atual, in-place no terminal embutido."""
        ws = self._current_workspace()
        if ws is None or not ws.folders:
            return
        try:
            from ..claude_sessions import list_sessions_for_paths
            cwd, _ = ws.launch_paths()
            paths = list({cwd, *ws.folders})
            sessions = list_sessions_for_paths(paths, limit=1)
        except Exception:
            log.exception("Falha ao listar última sessão do %s", ws.id)
            return
        if not sessions:
            QMessageBox.information(
                self,
                "Sem sessões",
                f"Nenhuma sessão registrada para o workspace '{ws.name}'.",
            )
            return
        s = sessions[0]
        self._launch_claude_for(ws, s.id, s.origin_cwd)

    def _export_session(self, session) -> None:
        """Exporta sessão JSONL como markdown — abre dialog com preview +
        opções de salvar arquivo e copiar pro clipboard."""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QDialog, QFileDialog, QPlainTextEdit, QPushButton

        from ..services.session_export import export_to_markdown

        try:
            md = export_to_markdown(session.path)
        except Exception:
            log.exception("Falha exportando sessão %s", session.id)
            QMessageBox.warning(
                self, "Falha", "Não foi possível ler o arquivo da sessão."
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Exportar sessão — {session.id[:8]}")
        dlg.resize(820, 600)
        v = QVBoxLayout(dlg)
        preview = QPlainTextEdit(md)
        preview.setReadOnly(False)
        v.addWidget(preview, stretch=1)

        row = QHBoxLayout()
        copy_btn = QPushButton("Copiar pra clipboard")
        save_btn = QPushButton("Salvar como…")
        close_btn = QPushButton("Fechar")
        row.addWidget(copy_btn)
        row.addWidget(save_btn)
        row.addStretch()
        row.addWidget(close_btn)
        v.addLayout(row)

        copy_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(preview.toPlainText())
        )
        def do_save():
            default = f"claude-session-{session.id[:8]}.md"
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Salvar markdown", default, "Markdown (*.md);;Todos (*)"
            )
            if not path:
                return
            try:
                Path(path).write_text(preview.toPlainText(), encoding="utf-8")
            except OSError as e:
                QMessageBox.warning(dlg, "Falha ao salvar", str(e))
        save_btn.clicked.connect(do_save)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec()

    def _show_sessions_search(self) -> None:
        from .sessions_search_dialog import SessionsSearchDialog
        dialog = SessionsSearchDialog(parent=self)
        dialog.session_chosen.connect(self._jump_to_search_hit)
        dialog.exec()

    def _jump_to_search_hit(self, hit) -> None:
        """Pula pro workspace que contém a pasta da sessão e retoma a sessão."""
        cwd = hit.project_path
        # Acha o workspace cujas folders contenham cwd, ou seja cwd
        match = None
        for ws in self.workspaces:
            for folder in ws.folders:
                if folder == cwd or cwd.startswith(folder + "/"):
                    match = ws
                    break
            if match:
                break
        if match is None:
            QMessageBox.information(
                self,
                "Workspace não encontrado",
                f"Não achei workspace contendo:\n{cwd}\n\n"
                f"Crie um workspace com essa pasta pra retomar.",
            )
            return
        # Foca workspace e retoma sessão internamente
        ws_item = self._find_workspace_item(match.id)
        if ws_item is not None:
            self.list_widget.setCurrentItem(ws_item)
        self._launch_claude_for(match, hit.session_id, cwd)

    # Spec dos panels do dock — adicionar um novo painel é só estender
    # essa lista. factory recebe MainWindow pra acessar dependencies.
    DOCK_PANEL_SPECS: list[DockPanelSpec] = [
        DockPanelSpec(
            panel_id="git",
            title="Git",
            factory=lambda mw: mw.details.git_panel(),
            default_open=True,
        ),
        DockPanelSpec(
            panel_id="memory",
            title="Memória",
            factory=lambda mw: MemoryPanel(),
            default_open=False,
        ),
        DockPanelSpec(
            panel_id="skills",
            title="Skills",
            factory=lambda mw: SkillsPanel(settings=mw.settings),
            default_open=False,
        ),
    ]

    def _build_right_dock(self) -> QWidget:
        self.dock_coord = DockCoordinator(
            self.settings, self.DOCK_PANEL_SPECS, self, self
        )
        dock = self.dock_coord.build()
        # Backward-compat: panels acessíveis via attrs nomeados (alguns
        # callers usam self._skills_panel etc.)
        for spec in self.DOCK_PANEL_SPECS:
            panel = self.dock_coord.panel(spec.panel_id)
            setattr(self, f"_{spec.panel_id}_panel", panel)
        self.dock_coord.panel_toggled.connect(
            lambda *_: self._schedule_layout_save()
        )
        return dock

    def _build_terminal_pane(self) -> QWidget:
        pane = QWidget()
        pane.setMinimumHeight(0)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setStyleSheet(
            "background: #161616; border-bottom: 1px solid #2a2a2a;"
        )
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        # Clique no header (fora dos botões) expande o terminal se
        # estiver minimizado
        def _on_header_click(_ev):
            if self._terminal_is_minimized():
                self._toggle_terminal()
        header.mousePressEvent = _on_header_click  # type: ignore[assignment]
        self._terminal_header = header
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)
        title = QLabel("Terminal")
        title.setStyleSheet("color: #888; font-size: 11px;")
        h.addWidget(title)
        h.addStretch()

        btn_css = (
            "QPushButton { background: transparent; color: #aaa; "
            "border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #6aa9e0; border-color: #3d6ea8; }"
            "QPushButton:disabled { color: #444; }"
        )
        # Ícones estilo Windows: minimizar (linha), maximizar (quadrado),
        # restaurar (quadrados sobrepostos)
        self._term_min_btn = QPushButton("—")
        self._term_min_btn.setToolTip("Minimizar terminal (Ctrl+J)")
        self._term_min_btn.setFixedWidth(28)
        self._term_min_btn.setStyleSheet(btn_css)
        self._term_min_btn.clicked.connect(self._toggle_terminal)
        h.addWidget(self._term_min_btn)

        self._term_max_btn = QPushButton("▢")
        self._term_max_btn.setToolTip("Maximizar terminal (esconder conteúdo)")
        self._term_max_btn.setFixedWidth(28)
        self._term_max_btn.setStyleSheet(btn_css)
        self._term_max_btn.clicked.connect(self._maximize_terminal)
        h.addWidget(self._term_max_btn)

        self._term_restore_btn = QPushButton("❐")
        self._term_restore_btn.setToolTip("Restaurar layout 50/50")
        self._term_restore_btn.setFixedWidth(28)
        self._term_restore_btn.setStyleSheet(btn_css)
        self._term_restore_btn.clicked.connect(self._restore_terminal)
        h.addWidget(self._term_restore_btn)

        layout.addWidget(header)

        self.terminal_host = QStackedWidget()
        self.terminal_host.setMinimumHeight(0)
        self._empty_terminal = QLabel(
            "Nenhum terminal aberto — clique em 'Abrir Claude' ou 'Abrir Terminal' "
            "para iniciar uma sessão. Cada workspace tem suas próprias abas."
        )
        self._empty_terminal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_terminal.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 28px;"
        )
        self._terminal_placeholder_idx = self.terminal_host.addWidget(self._empty_terminal)
        layout.addWidget(self.terminal_host, stretch=1)

        return pane

    def _build_sidebar(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("<b>WORKSPACES</b>"))

        self.list_widget = QTreeWidget()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(True)
        self.list_widget.setIndentation(14)
        self.list_widget.setExpandsOnDoubleClick(False)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.itemClicked.connect(self._on_tree_item_clicked)
        self.list_widget.itemActivated.connect(self._on_tree_item_activated)
        self.list_widget.setStyleSheet(
            "QTreeWidget { background: transparent; border: 0; color: #e6e6e6; }"
            "QTreeWidget::item { padding: 4px 4px; color: #e6e6e6; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
            "QTreeWidget::item:selected:hover { background: #4a82c5; color: #fff; }"
        )
        from PySide6.QtGui import QColor, QPalette
        pal = self.list_widget.palette()
        for grp in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(grp, QPalette.ColorRole.Text, QColor("#e6e6e6"))
            pal.setColor(grp, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            pal.setColor(grp, QPalette.ColorRole.Highlight, QColor("#3d6ea8"))
        self.list_widget.setPalette(pal)
        layout.addWidget(self.list_widget, stretch=1)

        # Spinner é gerido pelo TerminalCoordinator (signal spinner_tick)

        add_btn = QPushButton("+ Novo Workspace")
        add_btn.setToolTip("Criar novo workspace (Ctrl+N)")
        add_btn.clicked.connect(self.add_workspace)
        layout.addWidget(add_btn)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2a2a2a;")
        layout.addWidget(sep)

        self.self_dev_btn = QPushButton("🔧 Hack este app")
        self.self_dev_btn.setToolTip(
            "Abre o Claude no diretório do próprio claude-workspaces pra iterar nele"
        )
        self.self_dev_btn.clicked.connect(self._launch_self_dev)
        layout.addWidget(self.self_dev_btn)

        return wrapper

    # ---------- listagem / filtro / badge ----------

    def refresh_list(self) -> None:
        current_id = None
        current_item = self.list_widget.currentItem()
        if current_item:
            data = current_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Workspace):
                current_id = data.id
            elif current_item.parent():
                pdata = current_item.parent().data(0, Qt.ItemDataRole.UserRole)
                if isinstance(pdata, Workspace):
                    current_id = pdata.id

        self.list_widget.clear()
        self.terminals_coord.state.tree_items.clear()

        for ws in self.workspaces:
            item = QTreeWidgetItem([self._item_label(ws)])
            item.setData(0, Qt.ItemDataRole.UserRole, ws)
            tip = ws.description or ""
            if ws.folders:
                tip = (tip + "\n\n" if tip else "") + "\n".join(ws.folders)
            if tip:
                item.setToolTip(0, tip)
            self.list_widget.addTopLevelItem(item)
            item.setExpanded(True)

        self._apply_filter(
            self.top_bar.search.text() if hasattr(self, "top_bar") else ""
        )

        # Reanexa abas de terminais já existentes
        for ws_id, area in self.terminals_coord._areas.items():
            ws_item = self._find_workspace_item(ws_id)
            if ws_item is None:
                continue
            for i in range(area.tabs.count()):
                widget = area.tabs.widget(i)
                if not isinstance(widget, TerminalWidget):
                    continue
                tab_id = id(widget)
                base_title = widget.property("_base_title") or area.tabs.tabText(i)
                self._add_terminal_child(
                    ws_item, tab_id, base_title,
                    self.terminals_coord.state.activity.get(tab_id, ("", False, base_title))[0],
                    self.terminals_coord.state.activity.get(tab_id, ("", False, base_title))[1],
                    widget.is_running(),
                )

        # Última sessão do Claude (se houver) como child — visível mesmo
        # sem terminal ativo. Duplo-clique retoma via `claude --resume`.
        for i in range(self.list_widget.topLevelItemCount()):
            ws_item = self.list_widget.topLevelItem(i)
            ws = ws_item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(ws, Workspace):
                continue
            last = self._last_session_for(ws)
            if last is not None:
                self._add_last_session_child(ws_item, last)

        if current_id:
            ws_item = self._find_workspace_item(current_id)
            if ws_item is not None and not ws_item.isHidden():
                self.list_widget.setCurrentItem(ws_item)
                return

        for i in range(self.list_widget.topLevelItemCount()):
            it = self.list_widget.topLevelItem(i)
            if not it.isHidden():
                self.list_widget.setCurrentItem(it)
                return

        self.details.show_empty()

    def _find_workspace_item(self, workspace_id: str) -> QTreeWidgetItem | None:
        for i in range(self.list_widget.topLevelItemCount()):
            it = self.list_widget.topLevelItem(i)
            ws = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(ws, Workspace) and ws.id == workspace_id:
                return it
        return None

    def _item_label(self, ws: Workspace) -> str:
        count = self.terminals_coord.state.running_counts.get(ws.id, 0)
        if count > 0:
            dot = "●" if count == 1 else f"●×{count}"
            return f"{dot} {ws.name}"
        return ws.name

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.list_widget.topLevelItemCount()):
            item = self.list_widget.topLevelItem(i)
            ws = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(ws, Workspace):
                continue
            # Inclui preview das sessões do Claude — assim o user encontra
            # workspace lembrando do prompt que rodou antes
            sess_text = self._session_text_for(ws) if needle else ""
            haystack = (
                f"{ws.name}\n{ws.description}\n{' '.join(ws.folders)}\n{sess_text}"
            ).lower()
            item.setHidden(bool(needle) and needle not in haystack)
        current = self.list_widget.currentItem()
        if current and current.isHidden():
            for i in range(self.list_widget.topLevelItemCount()):
                it = self.list_widget.topLevelItem(i)
                if not it.isHidden():
                    self.list_widget.setCurrentItem(it)
                    return

    def _session_text_for(self, ws: Workspace) -> str:
        """Delega pro WorkspaceCoordinator (cache lazy)."""
        return self.workspaces_coord.session_text_for(ws)

    def _invalidate_session_cache(self, ws_id: str | None = None) -> None:
        self.workspaces_coord.invalidate_cache(ws_id)

    def _search_submit(self) -> None:
        """Enter na busca: foca o primeiro workspace visível."""
        rows = self._visible_rows()
        if not rows:
            return
        self.list_widget.setCurrentRow(rows[0])
        self.list_widget.setFocus()

    def _refresh_item_label(self, workspace_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            ws = item.data(Qt.ItemDataRole.UserRole)
            if ws.id == workspace_id:
                item.setText(self._item_label(ws))
                break

    def _on_workspace_running(self, workspace_id: str, count: int) -> None:
        if count <= 0:
            self.terminals_coord.state.running_counts.pop(workspace_id, None)
        else:
            self.terminals_coord.state.running_counts[workspace_id] = count
        self._refresh_item_label(workspace_id)

    # ---------- seleção / settings ----------

    def _on_selection_changed(self, current, _previous) -> None:
        if self.content_stack.currentIndex() != 0:
            self.content_stack.setCurrentIndex(0)
        if current is None:
            self.details.show_empty()
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)
            self._broadcast_workspace(None)
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        ws: Workspace | None = None
        if isinstance(data, Workspace):
            ws = data
        elif current.parent() is not None:
            pdata = current.parent().data(0, Qt.ItemDataRole.UserRole)
            if isinstance(pdata, Workspace):
                ws = pdata
        if ws is None:
            return
        self.details.show_workspace(ws)
        self._broadcast_workspace(ws)
        self._sync_terminal_for(ws)
        if self._plugin_host is not None:
            self._plugin_host.publish("workspace.opened", {"workspaceId": ws.id})

    def _broadcast_workspace(self, workspace: Workspace | None) -> None:
        """Delega pro DockCoordinator."""
        self.dock_coord.broadcast_workspace(workspace)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        # Clique simples numa aba ativa/em ação (tab_id) já foca a aba.
        # Sessões históricas (ClaudeSession) continuam exigindo duplo-clique
        # pra evitar relaunch acidental.
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, int):  # só tab_id de aba viva
            return
        pdata = item.parent().data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(pdata, Workspace):
            return
        self._focus_terminal_tab(pdata, data)

    def _on_tree_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        # Double-click ou Enter — sessão histórica retoma via --resume
        # NO TERMINAL INTERNO; terminal vivo foca a aba existente.
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        pdata = item.parent().data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(pdata, Workspace):
            return
        if isinstance(data, ClaudeSession):
            # Rota pelo launcher embutido (mesmo fluxo do botão Retomar
            # do card) — não abre Konsole externo
            self._launch_claude_for(pdata, data.id, data.origin_cwd)
            return
        if not isinstance(data, int):  # tab_id
            return
        self._focus_terminal_tab(pdata, data)

    def _focus_terminal_tab(self, workspace: Workspace, tab_id: int) -> None:
        area = self.terminals_coord._areas.get(workspace.id)
        if area is None:
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                break

    def _last_session_for(self, ws: Workspace) -> ClaudeSession | None:
        if not ws.folders:
            return None
        try:
            cwd, _ = ws.launch_paths()
            paths = list({cwd, *ws.folders})
            sessions = list_sessions_for_paths(paths, limit=1)
        except Exception:
            log.exception("Falha ao listar sessões do workspace %s", ws.id)
            return None
        return sessions[0] if sessions else None

    def _add_last_session_child(
        self, ws_item: QTreeWidgetItem, session: ClaudeSession
    ) -> None:
        from PySide6.QtGui import QBrush, QColor

        label = "↻ " + session.label(max_preview=40)
        child = QTreeWidgetItem([label])
        child.setData(0, Qt.ItemDataRole.UserRole, session)
        child.setToolTip(
            0, f"Última sessão — duplo-clique pra retomar ({session.id})"
        )
        child.setForeground(0, QBrush(QColor("#9aa3b3")))
        ws_item.addChild(child)
        ws_item.setExpanded(True)

    def _show_settings(self) -> None:
        # Garante que estamos na view de workspaces (settings vive no
        # content_stack interno do body_splitter)
        self.main_stack.setCurrentWidget(self.body_splitter)
        self.activity_bar.set_active(VIEW_SETTINGS)
        self.content_stack.setCurrentWidget(self._settings_scroll)

    def _show_workspaces(self) -> None:
        self.main_stack.setCurrentWidget(self.body_splitter)
        self.activity_bar.set_active(VIEW_WORKSPACES)
        self.content_stack.setCurrentIndex(0)
        current = self.list_widget.currentItem()
        if current:
            ws = current.data(Qt.ItemDataRole.UserRole)
            self.details.show_workspace(ws)
            self._sync_terminal_for(ws)

    # ---------- terminal ----------

    def _sync_terminal_for(self, workspace: Workspace) -> None:
        area = self.terminals_coord._areas.get(workspace.id)
        if area is not None:
            self.terminal_host.setCurrentWidget(area)
        else:
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)

    def _get_terminal_area(self, workspace: Workspace) -> TerminalArea:
        """Compat: delega pro TerminalCoordinator."""
        return self.terminals_coord.get_or_create_area(workspace)

    def _on_area_created(self, workspace_id: str, area: TerminalArea) -> None:
        """TerminalCoordinator criou uma nova area — adiciona no host."""
        self.terminal_host.addWidget(area)

    def _handle_tab_activity(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
        workspace_id: str,
    ) -> None:
        """Slot do TerminalCoordinator.tab_activity_changed.
        Atualiza o tree child. Inbox/spinner já foram tratados no coord."""
        # Despacha eventos pro plugin bus (session.created/status-changed/completed)
        self._dispatch_session_events(
            tab_id, workspace_id, title, is_working, is_running
        )

        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is None:
            return
        if tab_id in self.terminals_coord.state.tree_items:
            self._update_terminal_child(tab_id, title, status, is_working, is_running)
        else:
            self._add_terminal_child(
                ws_item, tab_id, title, status, is_working, is_running
            )

    def _handle_tab_removed(self, tab_id: int) -> None:
        """Slot do TerminalCoordinator.tab_removed.
        Estado já foi limpo no coord; aqui só remove o item do tree."""
        # Limpa cache do plugin host e dispara session.completed se ainda não foi
        if self._plugin_host is not None:
            cached = self._plugin_session_cache.pop(tab_id, None)
            if cached and cached.get("status") != "completed":
                duration_ms = max(
                    0, int((time.monotonic() - cached["created_at_mono"]) * 1000)
                )
                self._publish_session_event(
                    "session.completed",
                    tab_id,
                    {"reason": "closed", "durationMs": duration_ms},
                )
        item = self.terminals_coord.state.tree_items.get(tab_id)
        if item is not None and item.parent() is not None:
            item.parent().removeChild(item)

    def _dispatch_session_events(
        self,
        tab_id: int,
        workspace_id: str,
        title: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        """Mantém o cache de sessões e despacha session.* pro plugin bus.

        Tradução: 1ª vez vendo tab_id → session.created. Mudança de status
        no cache → session.status-changed. is_running=False → session.completed."""
        if self._plugin_host is None:
            return
        ws = self.workspaces_coord.find_by_id(workspace_id)
        ws_name = ws.name if ws else workspace_id
        new_status = self._plugin_session_status_for(is_working, is_running)
        cached = self._plugin_session_cache.get(tab_id)
        now = time.monotonic()
        if cached is None:
            self._plugin_session_cache[tab_id] = {
                "workspace_id": workspace_id,
                "workspace_name": ws_name,
                "status": new_status,
                "title": title,
                "created_at_mono": now,
                "last_change_mono": now,
            }
            self._publish_session_event(
                "session.created",
                tab_id,
                {
                    "workspaceId": workspace_id,
                    "createdAt": datetime.now().isoformat(timespec="seconds"),
                },
            )
            return

        # Atualiza título sempre (parte do estado, não evento)
        cached["title"] = title
        cached["workspace_name"] = ws_name

        old_status = cached["status"]
        if new_status != old_status:
            duration_ms = max(
                0, int((now - cached["last_change_mono"]) * 1000)
            )
            cached["status"] = new_status
            cached["last_change_mono"] = now
            self._publish_session_event(
                "session.status-changed",
                tab_id,
                {
                    "oldStatus": old_status,
                    "newStatus": new_status,
                    "durationMs": duration_ms,
                },
            )
            if new_status == "completed":
                total_ms = max(
                    0, int((now - cached["created_at_mono"]) * 1000)
                )
                self._publish_session_event(
                    "session.completed",
                    tab_id,
                    {"reason": "ended", "durationMs": total_ms},
                )

    def _on_spinner_tick(self, spinner_char: str) -> None:
        """Slot do TerminalCoordinator.spinner_tick — atualiza children
        que estão working com o frame atual."""
        for tab_id, (status, working, title) in list(self.terminals_coord.state.activity.items()):
            if working:
                self._update_terminal_child(tab_id, title, status, True, True)

    def _show_inbox(self) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu
        entries = self.terminals_coord.inbox_entries()
        if not entries:
            menu = QMenu(self)
            empty = QAction("(nenhum console aguardando)", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            menu.exec_(self.top_bar.mapToGlobal(self.top_bar.rect().bottomRight()))
            return
        menu = QMenu(self)
        for tab_id, info in list(entries.items()):
            ws = self.workspaces_coord.find_by_id(info["workspace_id"])
            ws_name = ws.name if ws else "?"
            label = f"{ws_name} · {info['title']}"
            if info.get("status"):
                sub = info["status"]
                if len(sub) > 60:
                    sub = sub[:59] + "…"
                label += f"  —  {sub}"
            act = QAction(label, menu)
            act.triggered.connect(
                lambda _checked=False, wid=info["workspace_id"], tid=tab_id:
                    self._focus_tab_from_inbox(wid, tid)
            )
            menu.addAction(act)
        menu.addSeparator()
        clear = QAction("Limpar inbox", menu)
        clear.triggered.connect(self.terminals_coord.clear_inbox)
        menu.addAction(clear)
        anchor = self.top_bar._inbox_btn
        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _focus_tab_from_inbox(self, workspace_id: str, tab_id: int) -> None:
        self.terminals_coord.remove_from_inbox(tab_id)
        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is not None:
            self.list_widget.setCurrentItem(ws_item)
        area = self.terminals_coord.area_for(workspace_id)
        if area is None:
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                break

    def _resolve_state(self, is_working: bool, is_running: bool) -> str:
        if not is_running:
            return STATE_DONE
        if is_working:
            return STATE_WORKING
        return STATE_IDLE

    def _terminal_widget_for(self, tab_id: int) -> TerminalWidget | None:
        for area in self.terminals_coord._areas.values():
            for i in range(area.tabs.count()):
                w = area.tabs.widget(i)
                if id(w) == tab_id and isinstance(w, TerminalWidget):
                    return w
        return None

    # Altura fixa do TerminalChildWidget (sincronizado com a constante lá)
    _CHILD_HEIGHT = 48

    def _add_terminal_child(
        self,
        ws_item: QTreeWidgetItem,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        child = QTreeWidgetItem()
        child.setData(0, Qt.ItemDataRole.UserRole, tab_id)
        child.setSizeHint(0, QSize(0, self._CHILD_HEIGHT))
        widget = TerminalChildWidget(title)
        full_title = title
        term = self._terminal_widget_for(tab_id)
        if term is not None:
            full_title = term.full_title() or title
        widget.set_title(title, full_title)
        state = self._resolve_state(is_working, is_running)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        ws_item.addChild(child)
        self.list_widget.setItemWidget(child, 0, widget)
        # Tarefas concluídas (processo finalizado) ficam ocultas na sidebar —
        # ainda acessíveis via "↻ última sessão" do workspace.
        child.setHidden(state == STATE_DONE)
        ws_item.setExpanded(True)
        self.terminals_coord.state.tree_items[tab_id] = child

    def _update_terminal_child(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        item = self.terminals_coord.state.tree_items.get(tab_id)
        if item is None:
            return
        widget = self.list_widget.itemWidget(item, 0)
        if not isinstance(widget, TerminalChildWidget):
            return
        full_title = title
        term = self._terminal_widget_for(tab_id)
        if term is not None:
            full_title = term.full_title() or title
        widget.set_title(title, full_title)
        state = self._resolve_state(is_working, is_running)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        # Esconde na sidebar quando a tarefa termina; reaparece se o processo
        # voltar a rodar (raro, mas mantém consistência).
        item.setHidden(state == STATE_DONE)

    def _launch_claude_for(
        self, workspace: Workspace, resume_session_id: str, cwd_override: str
    ) -> None:
        terminal = self.launch_coord.launch_claude(
            workspace, resume_session_id, cwd_override
        )
        if terminal is not None:
            area = self.terminals_coord.area_for(workspace.id)
            if area is not None:
                self.terminal_host.setCurrentWidget(area)

    def _handoff_session(self, workspace: Workspace, session) -> None:
        self.launch_coord.handoff_session(workspace, session)

    def _launch_shell_for(self, workspace: Workspace) -> None:
        terminal = self.launch_coord.launch_shell(workspace)
        if terminal is not None:
            area = self.terminals_coord.area_for(workspace.id)
            if area is not None:
                self.terminal_host.setCurrentWidget(area)

    def _cleanup_terminal_for(self, workspace_id: str) -> None:
        if self._plugin_host is not None:
            self._plugin_host.publish(
                "workspace.closed", {"workspaceId": workspace_id}
            )
        area = self.terminals_coord.cleanup_area(workspace_id)
        if area is None:
            return
        self.terminal_host.removeWidget(area)
        area.deleteLater()
        if self.terminal_host.count() == 1:
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)

    # ---------- tarefas ----------

    def _open_file_in_editor(self, abs_path: str) -> None:
        from .git_panel import open_path_in_editor
        editor = self.settings.vscode_command or "code"
        try:
            open_path_in_editor(abs_path, editor)
        except FileNotFoundError:
            QMessageBox.warning(
                self,
                "Editor não encontrado",
                f"Comando '{editor}' não está no PATH. Ajuste em Configurações.",
            )

    # ---------- CRUD de workspace ----------

    def _launch_self_dev(self) -> None:
        repo = find_app_repo_root()
        if not repo:
            log.warning("Repo root não encontrado para self-dev")
            QMessageBox.warning(
                self,
                "Não foi possível localizar o repo",
                "Esse botão só funciona quando o app está rodando direto do código-fonte "
                "(com pyproject.toml acessível).",
            )
            return
        try:
            launch_claude_in_dir(repo, self.settings)
        except LauncherError as e:
            log.exception("Falha em self-dev launch")
            QMessageBox.warning(self, "Falha ao abrir Claude", str(e))

    def add_workspace(self) -> None:
        dialog = WorkspaceDialog(parent=self)
        if not dialog.exec():
            return
        ws = dialog.workspace()
        if not ws.name:
            QMessageBox.warning(self, "Workspace inválido", "O nome não pode ficar vazio.")
            return
        self.workspaces_coord.add(ws)
        tpl = dialog.selected_template()
        if (
            dialog.init_claude_md()
            and tpl is not None
            and tpl.claude_md
            and ws.folders
        ):
            self._apply_template_claude_md(ws, tpl)

    def _apply_template_claude_md(self, workspace: Workspace, template) -> None:
        target = Path(workspace.folders[0]) / "CLAUDE.md"
        if target.exists():
            reply = QMessageBox.question(
                self,
                "CLAUDE.md já existe",
                f"{target} já existe. Sobrescrever?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            target.write_text(template.claude_md, encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Falha ao gravar CLAUDE.md", str(e))

    def edit_workspace(self, workspace: Workspace) -> None:
        dialog = WorkspaceDialog(workspace=workspace, parent=self)
        if not dialog.exec():
            return
        updated = dialog.workspace()
        if self.workspaces_coord.replace(updated):
            self.details.show_workspace(updated)

    def delete_workspace(self, workspace: Workspace) -> None:
        if not self.workspaces_coord.confirm_delete(workspace, parent=self):
            return
        # _cleanup_terminal_for é chamado via workspace_deleted signal
        self.workspaces_coord.delete(workspace.id)

    # ---------- persistência ----------


    def _restore_geometry(self) -> None:
        geom = self.settings.window_geometry
        if geom and len(geom) == 4:
            x, y, w, h = geom
            if w > 200 and h > 200:
                self.setGeometry(x, y, w, h)
                return
        self.resize(1200, 780)

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self._persist_layout()
        except Exception:
            log.exception("Falha ao salvar geometria/splitters")
        try:
            if self._plugin_host is not None:
                self._plugin_host.shutdown()
        except Exception:
            log.exception("Falha desligando plugin host")
        super().closeEvent(event)

    def _init_plugin_host(self) -> None:
        """Sobe o subsistema de plugins. Falha aqui não derruba o app — o
        host vira `None` e o resto roda normal."""
        try:
            from ..plugin_api import Session as PluginSession
            from ..plugin_api import Workspace as PluginWorkspace
            from ..services.plugin_host import PluginHost

            # Cache local de sessões observadas (tab_id → metadados).
            # Atualizado por _handle_tab_activity; serve como fonte de verdade
            # pro provider de ctx.sessions.
            self._plugin_session_cache: dict[int, dict] = {}

            def ws_to_plugin(ws: Workspace) -> PluginWorkspace:
                return PluginWorkspace(
                    id=ws.id, name=ws.name, folders=tuple(ws.folders)
                )

            def list_ws() -> list[PluginWorkspace]:
                return [ws_to_plugin(w) for w in self.workspaces_coord.workspaces]

            def current_ws() -> PluginWorkspace | None:
                ws = self._current_workspace()
                return ws_to_plugin(ws) if ws else None

            def list_sessions(status_filter: str | None) -> list[PluginSession]:
                out: list[PluginSession] = []
                for tab_id, meta in self._plugin_session_cache.items():
                    if status_filter and meta["status"] != status_filter:
                        continue
                    out.append(
                        PluginSession(
                            id=str(tab_id),
                            workspace_id=meta["workspace_id"],
                            workspace_name=meta["workspace_name"],
                            status=meta["status"],
                            last_message=meta.get("title"),
                        )
                    )
                return out

            def focus_session(session_id: str) -> None:
                # Tab IDs vivem como inteiros; recebemos string da API.
                try:
                    tab_id = int(session_id)
                except ValueError:
                    return
                meta = self._plugin_session_cache.get(tab_id)
                if meta is None:
                    return
                self._focus_tab_from_inbox(meta["workspace_id"], tab_id)

            self._plugin_host = PluginHost(
                ws_list_provider=list_ws,
                ws_current_provider=current_ws,
                sessions_list_provider=list_sessions,
                session_focus_fn=focus_session,
            )
            self._plugin_host.notifications.connect(self._on_plugin_notification)
            # PluginsView dispara load/unload do runtime quando o usuário
            # instala, desinstala, habilita ou desabilita pela UI.
            self.plugins_view.set_runtime_reloader(self._reload_plugin_runtime)
            # commit.created vem do GitPanel quando o usuário commita pela UI.
            # Commits feitos por fora (terminal, IDE) não geram evento — limitação
            # aceitável; quando vier integração com FileSystemWatcher no .git/HEAD
            # isso pode ser ampliado.
            try:
                git_panel = self.details.git_panel()
                git_panel.commit_created.connect(self._on_commit_created)
            except Exception:
                log.exception("Falha conectando commit_created ao plugin host")
            log.info(
                "Plugin host iniciado (%d plugin(s) carregado(s))",
                len(self._plugin_host.runtime._modules),
            )
        except Exception:
            log.exception("Falha iniciando plugin host — plugins ficam desligados")

    def _on_commit_created(
        self, workspace_id: str, _folder: str, sha: str, message: str
    ) -> None:
        if self._plugin_host is None:
            return
        self._plugin_host.publish(
            "commit.created",
            {"workspaceId": workspace_id, "sha": sha, "message": message},
        )

    def _reload_plugin_runtime(self, plugin_id: str, action: str) -> None:
        """Aciona o runtime quando a PluginsView muda o estado do plugin.

        action: 'load' (depois de install/enable) ou 'unload' (uninstall/disable)."""
        if self._plugin_host is None:
            return
        runtime = self._plugin_host.runtime
        if action == "unload":
            runtime.unload(plugin_id)
            return
        inst = self._plugin_host.registry.get(plugin_id)
        if inst is None:
            log.warning("Reloader: plugin %s não está no registry", plugin_id)
            return
        # `load` é idempotente; pra reinstalação descarrega antes
        runtime.unload(plugin_id)
        errs = runtime.load(inst)
        for e in errs:
            log.warning("Plugin %s ao recarregar: %s", plugin_id, e)

    def _open_plugin_palette(self) -> None:
        """Ctrl+P: dialog com comandos declarados por plugins habilitados."""
        if self._plugin_host is None:
            return
        from .plugin_palette_dialog import PluginPaletteDialog

        dlg = PluginPaletteDialog(self._plugin_host, parent=self)
        dlg.exec()

    def _on_plugin_notification(
        self, plugin_id: str, kind: str, payload: dict
    ) -> None:
        """Encaminha ui.notify/toast/badge dos plugins. Ainda mínimo:
        loga; integração com bandeja/inbox vem depois."""
        log.info("plugin %s %s: %s", plugin_id, kind, payload)

    def _plugin_session_status_for(self, is_working: bool, is_running: bool) -> str:
        """Mapeia o estado interno (working/running) pros status da spec.

        Tabela:
        - running + working → 'running'
        - running + idle    → 'awaiting-input'
        - !running          → 'completed'
        """
        if not is_running:
            return "completed"
        return "running" if is_working else "awaiting-input"

    def _publish_session_event(
        self, event: str, tab_id: int, extra: dict | None = None
    ) -> None:
        """Helper: monta payload com `sessionId` e despacha pro bus."""
        if self._plugin_host is None:
            return
        payload = {"sessionId": str(tab_id)}
        if extra:
            payload.update(extra)
        self._plugin_host.publish(event, payload)
