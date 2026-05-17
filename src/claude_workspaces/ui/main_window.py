import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..claude_sessions import ClaudeSession, list_sessions_for_paths
from ..errors import LaunchError
from ..launchers import (
    LauncherError,
    find_app_repo_root,
    launch_claude_in_dir,
)
from ..logging_utils import log_exceptions
from ..models import Workspace
from ..services.quick_open import find_files
from ..services.system_open import open_in_file_manager
from ..session_persistence import (
    SavedSession,
    load_saved_sessions,
    save_sessions,
)
from ..settings import Settings
from .activity_bar import (
    VIEW_APPS,
    VIEW_CATALOG,
    VIEW_HOOKS,
    VIEW_MCP,
    VIEW_PLUGINS,
    VIEW_SETTINGS,
    VIEW_WORKSPACES,
    ActivityBar,
)
from .builders import SidebarBuilder, TerminalPaneBuilder
from .builders.shortcuts_installer import install_shortcuts
from .coordinators import (
    DockCoordinator,
    LaunchCoordinator,
    PluginCoordinator,
    TerminalCoordinator,
    WorkspaceCoordinator,
)
from .git_panel import open_path_in_editor
from .launch_claude_dialog import LaunchClaudeDialog  # noqa: F401  (importado p/ tests)
from .memory_panel import MemoryPanel
from .panels import DockPanelSpec
from .session_export_dialog import open_session_export_dialog
from .settings_panel import SettingsPanel
from .shortcuts_dialog import ShortcutsDialog
from .skills_panel import SkillsPanel
from .terminal_area import TerminalArea
from .terminal_child_widget import (
    STATE_DONE,
    STATE_IDLE,
    STATE_WORKING,
    TerminalChildWidget,
)
from .terminal_widget import TerminalWidget
from .theme import (
    LAYOUT_SAVE_DEBOUNCE_MS,
    SIDEBAR_DEFAULT_W,
    SPLITTER_HANDLE_W,
    TERMINAL_HEADER_MIN_H,
)
from .top_bar import TopBar
from .views import AppsView, CatalogView, HooksView, McpView, PluginsView
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
        self.plugin_coord = PluginCoordinator(
            workspace_lookup=self.workspaces_coord.find_by_id,
            current_workspace_fn=self._current_workspace,
            all_workspaces_fn=lambda: self.workspaces_coord.workspaces,
            focus_tab_fn=self._focus_tab_from_inbox,
            parent=self,
        )

        # Shadow attrs (defaults — sobrescritos pelo restore se houver)
        self._terminal_placeholder_idx: int = 0
        self._sidebar_last_size: int = SIDEBAR_DEFAULT_W
        self._terminal_last_size: int = 520
        self._content_last_size: int = 380
        # tab_id → título base (sem sufixo). Quando dois Claude começam com
        # o mesmo primeiro prompt, o mais novo ganha sufixo " (2)" pra
        # diferenciar visualmente.
        self._tab_base_titles: dict[int, str] = {}

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
        self.terminals_coord.inbox_alert.connect(self._on_inbox_alert)
        self.launch_coord.sessions_refresh_requested.connect(
            self.details.refresh_sessions_soon
        )

        # Notificações nativas (tray) + reminder config a partir das settings
        self._tray: QSystemTrayIcon | None = None
        self._init_tray()
        self.terminals_coord.set_reminder_interval(
            self.settings.notify_reminder_seconds,
            enabled=self.settings.notify_reminder_enabled,
        )

        self._restore_geometry()
        self.refresh_list()
        # Plugin host depende do PluginsView e do GitPanel (ambos só existem
        # depois do _build_ui), por isso o init é tardio.
        self.plugin_coord.init(self.plugins_view, self.details.git_panel())
        # ctx.ui.notify/toast → toast nativo. Sem isso plugins viram silenciosos.
        self.plugin_coord.notification_received.connect(self._on_plugin_notification)
        # Restaura sessões Claude da execução anterior — defer pra deixar
        # a janela pintar primeiro, evitando flicker do dialog de launch.
        QTimer.singleShot(0, self._restore_sessions)

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
        self.body_splitter.setHandleWidth(SPLITTER_HANDLE_W)
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
        self.right_splitter.setHandleWidth(SPLITTER_HANDLE_W)
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
        self.settings_panel.settings_saved.connect(self._on_settings_saved)
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
        self.plugins_view = PluginsView(settings=self.settings)
        self.main_stack.addWidget(self.plugins_view)             # 4: plugins
        self.apps_view: AppsView | None = None  # lazy: QtWebEngine pesa
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
        self._layout_save_timer.setInterval(LAYOUT_SAVE_DEBOUNCE_MS)
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

    @log_exceptions(message="Falha ao persistir layout ao vivo")
    def _persist_layout(self) -> None:
        self.settings.body_splitter_sizes = list(self.body_splitter.sizes())
        self.settings.right_splitter_sizes = list(self.right_splitter.sizes())
        self.settings.workspace_columns_sizes = self.details.columns_sizes()
        g = self.geometry()
        self.settings.window_geometry = [g.x(), g.y(), g.width(), g.height()]
        self.settings.save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "_layout_save_timer"):
            self._layout_save_timer.start()

    def _install_shortcuts(self) -> None:
        install_shortcuts(self)

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
            target = self._sidebar_last_size or SIDEBAR_DEFAULT_W
            self.body_splitter.setSizes([target, max(sum(sizes) - target, 200)])
        self._schedule_layout_save()

    def _terminal_header_height(self) -> int:
        """Altura do header do terminal — usado como 'min height' quando
        minimizado (barra fica visível e clicável pra restaurar)."""
        if hasattr(self, "_terminal_header"):
            return max(self._terminal_header.sizeHint().height(), TERMINAL_HEADER_MIN_H)
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
        elif view_id == VIEW_APPS:
            if self.apps_view is None:
                self.apps_view = AppsView(settings=self.settings)
                self.main_stack.addWidget(self.apps_view)
            self.main_stack.setCurrentWidget(self.apps_view)
            self.apps_view.refresh()

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
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        try:
            open_in_file_manager(ws.folders[0])
        except LaunchError as e:
            QMessageBox.warning(self, "Falha ao abrir pasta", str(e))

    def _copy_primary_folder(self) -> None:
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        QGuiApplication.clipboard().setText(ws.folders[0])

    def _show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def _resume_last_session(self) -> None:
        """Ctrl+Shift+R: retoma a sessão Claude mais recente do workspace
        atual, in-place no terminal embutido."""
        ws = self._current_workspace()
        if ws is None or not ws.folders:
            return
        try:
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
        """Exporta sessão JSONL como markdown — abre dialog com preview."""
        open_session_export_dialog(session, parent=self)

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
        def on_header_click() -> None:
            if self._terminal_is_minimized():
                self._toggle_terminal()

        builder = TerminalPaneBuilder(
            on_min_click=self._toggle_terminal,
            on_max_click=self._maximize_terminal,
            on_restore_click=self._restore_terminal,
            on_header_click=on_header_click,
        ).build()
        self._terminal_header = builder.header
        self._term_min_btn = builder.min_btn
        self._term_max_btn = builder.max_btn
        self._term_restore_btn = builder.restore_btn
        self.terminal_host = builder.host
        self._empty_terminal = builder.empty_label
        self._terminal_placeholder_idx = builder.placeholder_idx
        return builder.pane

    def _build_sidebar(self) -> QWidget:
        builder = SidebarBuilder(
            on_current_changed=self._on_selection_changed,
            on_item_clicked=self._on_tree_item_clicked,
            on_item_activated=self._on_tree_item_activated,
            on_add_clicked=self.add_workspace,
            on_self_dev_clicked=self._launch_self_dev,
        ).build()
        self.list_widget = builder.list_widget
        self.self_dev_btn = builder.self_dev_btn
        return builder.wrapper

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
        self.plugin_coord.dispatch_workspace_opened(ws.id)

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
        self.plugin_coord.dispatch_session_event(
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
        self.plugin_coord.dispatch_tab_removed(tab_id)
        item = self.terminals_coord.state.tree_items.get(tab_id)
        parent_item = item.parent() if item is not None else None
        if item is not None and parent_item is not None:
            parent_item.removeChild(item)
        self._tab_base_titles.pop(tab_id, None)
        # Aba que saiu pode ter sido a única causa de colisão — re-disambigua
        if parent_item is not None:
            self._refresh_workspace_child_titles(parent_item)

    def _on_spinner_tick(self, spinner_char: str) -> None:
        """Slot do TerminalCoordinator.spinner_tick — atualiza children
        que estão working com o frame atual."""
        for tab_id, (status, working, title) in list(self.terminals_coord.state.activity.items()):
            if working:
                self._update_terminal_child(tab_id, title, status, True, True)

    def _on_settings_saved(self) -> None:
        """Re-aplica configs que afetam coordinators / tray ao salvar."""
        self.terminals_coord.set_reminder_interval(
            self.settings.notify_reminder_seconds,
            enabled=self.settings.notify_reminder_enabled,
        )
        if self.settings.notify_native_enabled and self._tray is None:
            self._init_tray()
        elif not self.settings.notify_native_enabled and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None

    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray indisponível — toasts nativos desabilitados")
            return
        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Claude Workspaces")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._on_tray_message_clicked)
        self._tray.show()
        self._last_alert_tab_id: int | None = None

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_message_clicked(self) -> None:
        """Click no toast → traz a aba aguardando pra frente."""
        tab_id = getattr(self, "_last_alert_tab_id", None)
        if tab_id is None:
            self.show()
            self.raise_()
            self.activateWindow()
            return
        info = self.terminals_coord.inbox_entries().get(tab_id)
        if info is None:
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self._focus_tab_from_inbox(info["workspace_id"], tab_id)

    def _on_inbox_alert(
        self, tab_id: int, info: dict, is_reminder: bool
    ) -> None:
        """Recebe alerta primário (working→idle) ou re-lembrete (timer).
        Dispara toast nativo se ativado."""
        if not self.settings.notify_native_enabled:
            return
        if self._tray is None:
            return
        ws = self.workspaces_coord.find_by_id(info.get("workspace_id", ""))
        ws_name = ws.name if ws else "Workspace"
        title_prefix = "🔁 Ainda aguardando" if is_reminder else "✅ Pronto"
        title = f"{title_prefix} — {ws_name}"
        body_parts: list[str] = []
        if info.get("title"):
            body_parts.append(str(info["title"]))
        if info.get("status"):
            status = str(info["status"])
            if len(status) > 90:
                status = status[:89] + "…"
            body_parts.append(status)
        body = "\n".join(body_parts) or "Console pronto pra próxima instrução."
        self._last_alert_tab_id = tab_id
        try:
            self._tray.showMessage(
                title, body, QSystemTrayIcon.MessageIcon.Information, 6000
            )
        except Exception:
            log.debug("showMessage falhou", exc_info=True)

    def _on_plugin_notification(
        self, plugin_id: str, kind: str, payload: dict
    ) -> None:
        """Sink final de ctx.ui.notify/toast/badge.

        Sem isso a chamada do plugin morre num log. Aqui:
        - notify/toast → tray.showMessage (se respeitando o toggle das settings)
        - badge → ignorado (não há ícone de plugin pra pintar)
        """
        if kind == "badge":
            log.debug(
                "plugin %s pediu badge=%s (sem renderizador — ignorado)",
                plugin_id, payload.get("count"),
            )
            return
        if not self.settings.notify_native_enabled:
            log.info(
                "plugin %s tentou %s mas notify_native_enabled=False — "
                "silenciado pelas settings | payload=%s",
                plugin_id, kind, payload,
            )
            return
        if self._tray is None:
            log.warning(
                "plugin %s pediu %s mas tray não está disponível | payload=%s",
                plugin_id, kind, payload,
            )
            return
        if kind == "notify":
            title = str(payload.get("title", plugin_id))
            body = str(payload.get("body", ""))
        else:  # toast
            level = str(payload.get("level", "info"))
            title = f"[{plugin_id}] {level}"
            body = str(payload.get("message", ""))
        icon = QSystemTrayIcon.MessageIcon.Information
        if payload.get("level") == "error":
            icon = QSystemTrayIcon.MessageIcon.Critical
        elif payload.get("level") == "warning":
            icon = QSystemTrayIcon.MessageIcon.Warning
        try:
            self._tray.showMessage(title, body, icon, 6000)
            log.info(
                "plugin %s notificou: %s | %s", plugin_id, title, body[:120]
            )
        except Exception:
            log.exception(
                "plugin %s: showMessage falhou (title=%r body=%r)",
                plugin_id, title, body,
            )

    def _show_inbox(self) -> None:
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
            if info.get("dismissed"):
                label = "👁  " + label  # marca visual de "já visto"
            entry_menu = menu.addMenu(label)
            focus_act = QAction("Focar console", entry_menu)
            focus_act.triggered.connect(
                lambda _c=False, wid=info["workspace_id"], tid=tab_id:
                    self._focus_tab_from_inbox(wid, tid)
            )
            entry_menu.addAction(focus_act)
            entry_menu.addSeparator()
            seen_act = QAction("Já vi — não me lembre", entry_menu)
            seen_act.triggered.connect(
                lambda _c=False, tid=tab_id:
                    self.terminals_coord.dismiss_inbox(tid)
            )
            entry_menu.addAction(seen_act)
            for minutes in (5, 15, 30):
                snz = QAction(f"Lembrar em {minutes} min", entry_menu)
                snz.triggered.connect(
                    lambda _c=False, tid=tab_id, s=minutes * 60:
                        self.terminals_coord.snooze_inbox(tid, s)
                )
                entry_menu.addAction(snz)
            entry_menu.addSeparator()
            remove_act = QAction("Remover do inbox", entry_menu)
            remove_act.triggered.connect(
                lambda _c=False, tid=tab_id:
                    self.terminals_coord.remove_from_inbox(tid)
            )
            entry_menu.addAction(remove_act)
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
        self._tab_base_titles[tab_id] = title
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
        # Reaplica sufixos de desambiguação no workspace inteiro (cobre o
        # caso de a nova aba colidir com outra que já estava sem sufixo).
        self._refresh_workspace_child_titles(ws_item)

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
        previous_base = self._tab_base_titles.get(tab_id)
        self._tab_base_titles[tab_id] = title
        display = self._compute_disambiguated_title(item.parent(), tab_id, title)
        widget.set_title(display, full_title)
        state = self._resolve_state(is_working, is_running)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        # Esconde na sidebar quando a tarefa termina; reaparece se o processo
        # voltar a rodar (raro, mas mantém consistência).
        item.setHidden(state == STATE_DONE)
        # Se o título base mudou, pode ter resolvido (ou criado) colisão
        # com siblings — re-desambigua o workspace inteiro.
        if previous_base != title:
            self._refresh_workspace_child_titles(item.parent())

    def _compute_disambiguated_title(
        self, ws_item: QTreeWidgetItem | None, tab_id: int, base_title: str
    ) -> str:
        """Se outros children do mesmo workspace têm o mesmo título base,
        retorna `base (N)` em ordem de criação (tab_id crescente).
        O mais antigo fica sem sufixo, os seguintes ganham (2), (3)..."""
        if not base_title or ws_item is None:
            return base_title
        siblings_same: list[int] = []
        for i in range(ws_item.childCount()):
            sib = ws_item.child(i)
            sib_id = sib.data(0, Qt.ItemDataRole.UserRole)
            if sib_id == tab_id:
                continue
            if self._tab_base_titles.get(sib_id, "") == base_title:
                siblings_same.append(int(sib_id))
        if not siblings_same:
            return base_title
        all_ids = sorted(siblings_same + [int(tab_id)])
        position = all_ids.index(int(tab_id))
        if position == 0:
            return base_title
        return f"{base_title} ({position + 1})"

    def _refresh_workspace_child_titles(
        self, ws_item: QTreeWidgetItem | None
    ) -> None:
        """Reaplica display title de cada child com a lógica de
        desambiguação. Barato — só N children por workspace."""
        if ws_item is None:
            return
        for i in range(ws_item.childCount()):
            sib = ws_item.child(i)
            sib_id = sib.data(0, Qt.ItemDataRole.UserRole)
            sib_widget = self.list_widget.itemWidget(sib, 0)
            if not isinstance(sib_widget, TerminalChildWidget):
                continue
            base = self._tab_base_titles.get(sib_id, "")
            if not base:
                continue
            full = base
            term = self._terminal_widget_for(int(sib_id))
            if term is not None:
                full = term.full_title() or base
            display = self._compute_disambiguated_title(ws_item, int(sib_id), base)
            sib_widget.set_title(display, full)

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
        self.plugin_coord.dispatch_workspace_closed(workspace_id)
        area = self.terminals_coord.cleanup_area(workspace_id)
        if area is None:
            return
        self.terminal_host.removeWidget(area)
        area.deleteLater()
        if self.terminal_host.count() == 1:
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)

    # ---------- tarefas ----------

    def _open_file_in_editor(self, abs_path: str) -> None:
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
        # _persist_layout já é @log_exceptions; chamada aqui não precisa
        # de outro wrapper.
        self._persist_layout()
        self._persist_active_sessions()
        self.plugin_coord.shutdown()
        super().closeEvent(event)

    @log_exceptions(message="Falha ao persistir sessões Claude ativas")
    def _persist_active_sessions(self) -> None:
        saved: list[SavedSession] = []
        for ws_id, area in self.terminals_coord._areas.items():
            for i in range(area.tabs.count()):
                widget = area.tabs.widget(i)
                if not isinstance(widget, TerminalWidget):
                    continue
                if not widget.is_running():
                    continue
                session_id = widget.claimed_session_id()
                cwd = widget.claude_cwd()
                if not session_id or not cwd:
                    continue
                saved.append(SavedSession(
                    workspace_id=ws_id,
                    session_id=session_id,
                    cwd=cwd,
                ))
        save_sessions(saved)

    @log_exceptions(message="Falha ao restaurar sessões Claude")
    def _restore_sessions(self) -> None:
        """Recria abas Claude que estavam ativas na última execução.
        Each entry vira `claude --resume <id>` no terminal embutido."""
        saved = load_saved_sessions()
        if not saved:
            return
        restored = 0
        for entry in saved:
            ws = self.workspaces_coord.find_by_id(entry.workspace_id)
            if ws is None:
                log.info(
                    "Sessão %s ignorada: workspace %s não existe mais",
                    entry.session_id, entry.workspace_id,
                )
                continue
            if not entry.session_file().exists():
                log.info(
                    "Sessão %s ignorada: JSONL inexistente em %s",
                    entry.session_id, entry.cwd,
                )
                continue
            try:
                self._launch_claude_for(ws, entry.session_id, entry.cwd)
                restored += 1
            except Exception:
                log.exception("Falha ao restaurar sessão %s", entry.session_id)
        if restored:
            log.info("Restauradas %d sessão(ões) Claude da execução anterior", restored)

    def _open_plugin_palette(self) -> None:
        """Ctrl+P: dialog com comandos declarados por plugins habilitados."""
        self.plugin_coord.open_palette(self)
