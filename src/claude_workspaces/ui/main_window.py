import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QGuiApplication,
    QIcon,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..claude_sessions import list_sessions_for_paths
from ..errors import LaunchError
from ..launchers import (
    LauncherError,
    find_app_repo_root,
    launch_claude_in_dir,
)
from ..logging_utils import log_exceptions
from ..models import Workspace
from ..repo_status_poller import RepoStatusPoller
from ..hook_manager import refresh_installed_hook
from ..services.desktop_notifier import DesktopNotifier
from .persistent_toast import PersistentToast, position_toasts
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
from .runner_area import RunnerArea
from .runner_edit_dialog import RunnerEditDialog
from .terminal_area import TerminalArea
from .terminal_child_widget import (
    STATE_AWAITING,
    STATE_DONE,
    STATE_IDLE,
    STATE_WORKING,
    TerminalChildWidget,
)
from .terminal_widget import TerminalWidget
from . import theme
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
        # Runners — paralelo a terminal_host. Cada workspace ganha uma
        # RunnerArea lazy; índice 0 do runner_host é um placeholder.
        self._runner_areas: dict[str, RunnerArea] = {}
        # Áreas de runners embutidas dentro de cada console (Claude tab).
        # workspace_id → { session_id → RunnerArea }. Console-scoped runners
        # rodam fora do painel inferior do workspace.
        self._console_runner_areas: dict[str, dict[str, RunnerArea]] = {}
        self._runner_placeholder_idx: int = 0
        # workspace_id → { runner_id → QTreeWidgetItem } (footer rows na sidebar)
        self._runner_tree_items: dict[str, dict[str, "QTreeWidgetItem"]] = {}
        # workspace_id → QTreeWidgetItem (header "Runners workspace")
        self._runner_group_items: dict[str, "QTreeWidgetItem"] = {}
        # (workspace_id, tab_id) → QTreeWidgetItem (header "Runners console")
        self._console_runner_group_items: dict[
            tuple[str, int], "QTreeWidgetItem"
        ] = {}
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
        self.terminals_coord.inbox_entry_removed.connect(
            self._on_inbox_entry_removed
        )
        self.launch_coord.sessions_refresh_requested.connect(
            self.details.refresh_sessions_soon
        )

        # Notificações nativas (tray) + reminder config a partir das settings
        self._tray: QSystemTrayIcon | None = None
        self._init_tray()
        # Notificador D-Bus com botões de ação (Abrir/Adiar/Já vi).
        # Se indisponível, _on_inbox_alert cai pro tray.showMessage.
        self._desktop_notifier: DesktopNotifier | None = None
        # tab_id → note_id D-Bus ativo. Permite fechar a notificação
        # proativamente quando o tab sai do inbox (voltou a trabalhar /
        # terminou / usuário clicou na aba), evitando banner stale.
        self._active_notifications: dict[int, int] = {}
        # tab_id → QTimer que re-emite a notif com replaces_id pra
        # ressuscitar o banner no KDE Plasma 6 (que transient-iza
        # notifs com action ignorando urgency/resident/timeout). Sem
        # isso o usuário perde o popup em ~6s. Cancelado quando a
        # entry sai do inbox ou o usuário clica na action.
        self._notification_keepalive: dict[int, QTimer] = {}
        # tab_id → PersistentToast — toast in-app frameless top-most que
        # garante visibilidade independente do que o KDE Plasma faz com a
        # notif D-Bus. Lifecycle 100% nosso: some só quando o usuário
        # clica (Abrir/X) ou o tab sai do inbox.
        self._active_toasts: dict[int, PersistentToast] = {}
        # tab_id → timestamp monotônico da última notif "Pronto" emitida.
        # Debounce: se um console oscila working↔idle rapidamente (ex:
        # Claude rodando hooks/sub-passos entre estados), suprime as
        # notif "Pronto" duplicadas dentro do _READY_DEBOUNCE_SEC. Não
        # afeta reminders (que rodam num timer separado).
        self._ready_alert_last: dict[int, float] = {}
        # Mantém o notify-hook.py instalado em sincronia com o packaged
        # (ex: versão com botão "Abrir console" via D-Bus).
        refresh_installed_hook()
        self._init_desktop_notifier()
        self.terminals_coord.set_reminder_interval(
            self.settings.notify_reminder_seconds,
            enabled=self.settings.notify_reminder_enabled,
        )
        TerminalWidget.set_idle_debounce_seconds(self.settings.idle_debounce_seconds)

        # Poller assíncrono pra branch+contagem de modificados ao lado de
        # cada console na sidebar. Criado antes de qualquer refresh pra
        # _add_terminal_child poder pedir status no primeiro paint.
        self._repo_poller = RepoStatusPoller(ttl_seconds=4.0, parent=self)
        self._repo_poller.status_ready.connect(self._on_repo_status_ready)
        self._repo_poll_timer = QTimer(self)
        self._repo_poll_timer.setInterval(5_000)
        self._repo_poll_timer.timeout.connect(self._refresh_terminal_git_info)
        self._repo_poll_timer.start()

        # Tick de 1s pra atualizar o cronômetro "Ocioso · 2m 30s" na
        # sidebar. Sempre ativo — o cost de iterar pelos tree_items uma
        # vez por segundo é desprezível e simplifica a lógica (não
        # precisa start/stop conforme transições de estado).
        self._idle_tick_timer = QTimer(self)
        self._idle_tick_timer.setInterval(1_000)
        self._idle_tick_timer.timeout.connect(self._on_idle_tick)
        self._idle_tick_timer.start()

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
        # Primeiro refresh um pouco depois pra dar tempo de o restore criar
        # os children e o claude_cwd estar disponível.
        QTimer.singleShot(800, self._refresh_terminal_git_info)

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

        # Body dock manager (QtAds): sidebar | conteúdo+terminal | right_dock.
        # O right_splitter interno (vertical: content / terminal) continua
        # sendo QSplitter pra preservar toda a lógica de min/max do terminal.
        from .dock_manager import WorkspaceDockManager
        self.body_dock = WorkspaceDockManager(self)

        self._sidebar = self._build_sidebar()
        self._sidebar.setMinimumWidth(0)

        # Splitter vertical interno ao painel central:
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

        # Dock direito (3ª coluna): Tarefas + Git + Skills colapsáveis
        self.right_dock = self._build_right_dock()
        self.right_dock.setMinimumWidth(0)

        # Monta os 3 docks. ORDEM IMPORTA: center primeiro — se left/right
        # entrarem antes, o QtAds não tem dock area pra ancorar e cria um
        # segundo dock area no mesmo lado (sidebar duplicando, etc).
        self._center_dock = self.body_dock.add_center(self.right_splitter, "Workspace")
        self._sidebar_dock = self.body_dock.add_left(self._sidebar, "Sidebar")
        self._right_panel_dock = self.body_dock.add_right(self.right_dock, "Ferramentas")

        # Restaura layout salvo (tamanhos das colunas). Fallback: ~240/760/340.
        # Schema=1: marca que a 0.54+ tem a ordem de criação correta
        # (center antes de left/right) — descarta states de versões antigas.
        _DOCK_SCHEMA = 1
        saved_state = (
            self.settings.body_dock_state
            if self.settings.body_dock_state_schema >= _DOCK_SCHEMA
            else ""
        )
        if not self.body_dock.restore_state_b64(saved_state):
            self._sidebar_dock.dockAreaWidget().resize(240, 600)
            self._right_panel_dock.dockAreaWidget().resize(340, 600)
        if self.settings.body_dock_state_schema < _DOCK_SCHEMA:
            self.settings.body_dock_state_schema = _DOCK_SCHEMA
            try:
                self.settings.save()
            except OSError:
                pass

        # ---------- Top-level shell: activity bar + main stack ----------
        # body_splitter (workspaces flow) é só uma das views do main_stack.
        # Catálogo / Hooks / MCP têm seus próprios widgets que ocupam o
        # mesmo espaço quando ativados pela activity bar.
        shell_row = QHBoxLayout()
        shell_row.setContentsMargins(0, 0, 0, 0)
        shell_row.setSpacing(0)

        self.activity_bar = ActivityBar()
        self.activity_bar.view_changed.connect(self._on_activity_view_changed)
        self.activity_bar.open_terminal_clicked.connect(self._launch_terminal_no_ctx)
        self.activity_bar.open_claude_no_ctx_clicked.connect(self._launch_claude_no_ctx)
        self.activity_bar.hack_app_clicked.connect(self._launch_self_dev)
        shell_row.addWidget(self.activity_bar)

        self.main_stack = QStackedWidget()
        # body_dock.widget = CDockManager — root da view de workspaces
        self.body_view = self.body_dock.widget
        self.main_stack.addWidget(self.body_view)                # 0: workspaces+settings
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

        # QtAds não tem signal único pra splitter interno; cobrimos os
        # eventos que importam (flutuar, fechar área) + resizeEvent já dispara
        self.body_dock.widget.floatingWidgetCreated.connect(
            lambda *_: self._schedule_layout_save()
        )
        self.body_dock.widget.dockAreasRemoved.connect(self._schedule_layout_save)
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
        self.settings.body_dock_state = self.body_dock.save_state_b64()
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
            and not self._is_section_header(self.list_widget.topLevelItem(i))
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
        self.body_dock.toggle("sidebar")
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
        self.body_dock.toggle("ferramentas")
        self._schedule_layout_save()

    def _current_workspace(self) -> Workspace | None:
        current = self.list_widget.currentItem()
        if current is None:
            return None
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Workspace):
            return data
        # Pode ser um filho (aba viva) — sobe pro parent
        parent = current.parent()
        if parent is not None:
            data = parent.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Workspace):
                return data
        return None

    def _on_activity_view_changed(self, view_id: str) -> None:
        """Activity bar trocou a view top-level. Carrega lazy."""
        if view_id == VIEW_WORKSPACES:
            self.main_stack.setCurrentWidget(self.body_view)
            self.content_stack.setCurrentIndex(0)
        elif view_id == VIEW_SETTINGS:
            self.main_stack.setCurrentWidget(self.body_view)
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
            icon="⎇",
            factory=lambda mw: mw.details.git_panel(),
            default_open=True,
        ),
        DockPanelSpec(
            panel_id="memory",
            title="Memória",
            icon="❏",
            factory=lambda mw: MemoryPanel(),
            default_open=False,
        ),
        DockPanelSpec(
            panel_id="skills",
            title="Skills",
            icon="✦",
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
        # Trocar a área visível (workspace) só re-sincroniza o runner host;
        # o % de plano não muda ao trocar de aba e a chamada extra só
        # gastava cota da /api/oauth/usage (rate limit agressivo).
        self.terminal_host.currentChanged.connect(
            lambda _i: self._sync_console_runner_host()
        )

        # Embute o host num QTabWidget com aba "Terminal" + "Runners".
        pane = builder.pane
        layout = pane.layout()
        layout.removeWidget(self.terminal_host)

        self._bottom_tabs = QTabWidget(pane)
        self._bottom_tabs.setDocumentMode(True)
        self._bottom_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._bottom_tabs.addTab(self.terminal_host, "Terminal")

        self.runner_host = QStackedWidget()
        self.runner_host.setMinimumHeight(0)
        runner_empty = QLabel("Selecione um workspace para ver seus runners.")
        runner_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        runner_empty.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 28px;"
        )
        self._runner_placeholder_idx = self.runner_host.addWidget(runner_empty)
        self._bottom_tabs.addTab(self.runner_host, "Runners workspace")

        # Terceira aba — runners de console (cada aba Claude tem seu próprio
        # painel; aqui aparece o painel do console ativo).
        self.console_runner_host = QStackedWidget()
        self.console_runner_host.setMinimumHeight(0)
        crh_empty = QLabel(
            "Abra um console Claude e, na barra do terminal, clique em "
            "▤ Runners para criar runners específicos desse console."
        )
        crh_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        crh_empty.setWordWrap(True)
        crh_empty.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 28px;"
        )
        self._console_runner_placeholder_idx = self.console_runner_host.addWidget(
            crh_empty
        )
        self._bottom_tabs.addTab(self.console_runner_host, "Runners (console)")

        layout.addWidget(self._bottom_tabs, stretch=1)
        return pane

    def _open_file_finder_dialog(self, initial_query: str = "") -> None:
        """Abre o modal de localizar arquivo usando as pastas do workspace
        atualmente selecionado. Pré-preenche com `initial_query` (o que o
        user já digitou no input da sidebar) e dispara a busca."""
        from .file_finder import FileFinderDialog

        ws = self._current_workspace()
        folders = list(ws.folders) if ws is not None else []
        if not folders:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                "Localizar arquivo",
                "Selecione um workspace com pastas configuradas pra buscar arquivos.",
            )
            return
        dlg = FileFinderDialog(folders, initial_query=initial_query, parent=self)
        dlg.open_file_requested.connect(self._open_file_in_editor)
        dlg.exec()
        # Limpa o input da sidebar pra próxima busca começar fresca.
        if hasattr(self, "_find_file_input"):
            self._find_file_input.clear()

    def _build_sidebar(self) -> QWidget:
        builder = SidebarBuilder(
            on_current_changed=self._on_selection_changed,
            on_item_clicked=self._on_tree_item_clicked,
            on_item_activated=self._on_tree_item_activated,
            on_add_clicked=self.add_workspace,
            on_version_clicked=self._show_release_notes,
            on_find_file=self._open_file_finder_dialog,
            on_search_workspaces=self._apply_filter,
        ).build()
        self._sidebar_search_input = builder.search_input
        self._find_file_input = builder.find_file_input
        self.list_widget = builder.list_widget
        self.version_label = builder.version_label
        self._context_status_label = builder.context_status_label
        self._context_status_container = builder.context_status_container
        self._context_status_refresh_btn = builder.context_status_refresh_btn
        self._context_status_refresh_btn.clicked.connect(
            self._on_context_status_refresh_clicked
        )
        self._actions_toggle_btn = builder.actions_toggle_btn
        self._actions_toggle_btn.clicked.connect(self._toggle_child_actions)
        self._refresh_actions_toggle_btn()
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_sidebar_context_menu)
        # Mantém o ícone do botão ▾/▸ sincronizado quando o usuário usa
        # o disclosure triangle nativo da QTreeWidget.
        self.list_widget.itemExpanded.connect(self._on_workspace_expanded)
        self.list_widget.itemCollapsed.connect(self._on_workspace_collapsed)
        return builder.wrapper

    def _refresh_actions_toggle_btn(self) -> None:
        visible = self.settings.show_terminal_actions
        self._actions_toggle_btn.setText("⌃" if visible else "⌄")
        self._actions_toggle_btn.setToolTip(
            ("Ocultar" if visible else "Mostrar")
            + " os botões ▶ Continuar / ⚙ Modo em cada console da sidebar."
            " As ações continuam acessíveis pelo menu de contexto (clique"
            " direito no console)."
        )

    def _toggle_child_actions(self) -> None:
        """Inverte a visibilidade global dos botões inline nos rows de
        console (▶ Continuar / ⚙ Modo). Persiste em settings e propaga
        pra todos os TerminalChildWidget existentes."""
        new_visible = not self.settings.show_terminal_actions
        self.settings.show_terminal_actions = new_visible
        try:
            self.settings.save()
        except OSError:
            log.exception("falha ao salvar show_terminal_actions")
        self._refresh_actions_toggle_btn()
        from .terminal_child_widget import TerminalChildWidget
        for i in range(self.list_widget.topLevelItemCount()):
            ws_item = self.list_widget.topLevelItem(i)
            for j in range(ws_item.childCount()):
                child = ws_item.child(j)
                widget = self.list_widget.itemWidget(child, 0)
                if isinstance(widget, TerminalChildWidget):
                    widget.set_actions_visible(new_visible)

    def _on_workspace_expanded(self, item: "QTreeWidgetItem") -> None:
        self._update_workspace_collapsed_icon(item, collapsed=False)
        self._persist_workspace_collapsed(item, collapsed=False)

    def _on_workspace_collapsed(self, item: "QTreeWidgetItem") -> None:
        self._update_workspace_collapsed_icon(item, collapsed=True)
        self._persist_workspace_collapsed(item, collapsed=True)

    def _persist_workspace_collapsed(
        self, item: "QTreeWidgetItem", collapsed: bool
    ) -> None:
        """Salva o estado expandido/colapsado no settings.
        Cobre tanto workspaces (top-level) quanto o submenu
        'Runners workspace' (dado = ('runner_group', ws_id, '')).
        Runner groups de console não são persistidos — o `tab_id` muda
        a cada execução, então não dá pra correlacionar entre sessões.
        Tolera falha de IO sem travar a UI."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Workspace):
            current = bool(self.settings.workspace_collapsed.get(data.id, False))
            if current == collapsed:
                return
            self.settings.workspace_collapsed[data.id] = collapsed
        elif (
            isinstance(data, tuple)
            and len(data) == 3
            and data[0] == "runner_group"
            and data[2] == ""
        ):
            ws_id = data[1]
            current = bool(self.settings.runner_group_collapsed.get(ws_id, False))
            if current == collapsed:
                return
            self.settings.runner_group_collapsed[ws_id] = collapsed
        else:
            return
        try:
            self.settings.save()
        except OSError:
            log.exception("falha ao salvar collapsed state")

    def _update_workspace_collapsed_icon(
        self, item: "QTreeWidgetItem", collapsed: bool
    ) -> None:
        from .runner_group_widget import RunnerGroupWidget
        from .workspace_item_widget import WorkspaceItemWidget

        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, WorkspaceItemWidget):
            widget.set_collapsed(collapsed)
        elif isinstance(widget, RunnerGroupWidget):
            widget.set_collapsed(collapsed)

    def _toggle_pin_workspace(self, ws: "Workspace") -> None:
        """Inverte ws.pinned e re-renderiza a sidebar (refresh_list é
        disparado via workspaces_coord.workspaces_changed)."""
        self.workspaces_coord.set_pinned(ws.id, not ws.pinned)

    def _on_sidebar_context_menu(self, pos) -> None:
        """Menu de contexto da sidebar — atalhos pra retomar trabalho do
        Claude sem precisar focar a aba e digitar 'continue' manualmente.
        Aparece em (a) item de console terminal e (b) item de workspace."""
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if isinstance(data, int):
            term = self._terminal_widget_for(data)
            if term is None:
                return
            tab_id = data
            rename_act = QAction("✏ Renomear sessão…", menu)
            rename_act.setToolTip(
                "Define um nome custom pra esse console — aparece na "
                "sidebar e nas notificações em vez do preview do primeiro "
                "prompt"
            )
            rename_act.triggered.connect(
                lambda _c=False, t=tab_id: self._rename_terminal_session(t)
            )
            menu.addAction(rename_act)
            menu.addSeparator()
            if term.is_running():
                self._add_session_info_actions(menu, term)
                continue_act = QAction("▶ Continuar este console", menu)
                continue_act.setToolTip("Manda 'continue' + Enter pro Claude desta aba")
                continue_act.triggered.connect(term.send_continue)
                menu.addAction(continue_act)
                menu.addSeparator()
                cycle_act = QAction("↹ Ciclar modo (Plan / Auto / …)", menu)
                cycle_act.setToolTip(
                    "Manda Shift+Tab pro Claude — cicla entre Plan, Auto-accept "
                    "e Default. Olha o indicador embaixo-direita do TUI pra ver "
                    "onde parou."
                )
                cycle_act.triggered.connect(term.send_cycle_mode)
                menu.addAction(cycle_act)
                effort_act = QAction("⏻ Trocar effort (/effort)", menu)
                effort_act.setToolTip("Abre o slash command /effort no prompt do Claude")
                effort_act.triggered.connect(term.send_open_effort)
                menu.addAction(effort_act)
                model_act = QAction("✦ Trocar modelo (/model)", menu)
                model_act.setToolTip("Abre o slash command /model no prompt do Claude")
                model_act.triggered.connect(term.send_open_model)
                menu.addAction(model_act)
                menu.addSeparator()
            close_act = QAction("✖ Encerrar/remover console", menu)
            close_act.setToolTip(
                "Encerra o processo (se rodando) e remove esta aba do terminal"
            )
            close_act.triggered.connect(
                lambda _c=False, t=tab_id: self._close_terminal_by_tab_id(t)
            )
            menu.addAction(close_act)
        elif isinstance(data, Workspace):
            ws = data
            pin_label = "📌 Desafixar workspace" if ws.pinned else "📌 Fixar workspace"
            pin_act = QAction(pin_label, menu)
            pin_act.setToolTip(
                "Move pra/de seção FIXADOS no topo da sidebar."
            )
            pin_act.triggered.connect(lambda _c=False, w=ws: self._toggle_pin_workspace(w))
            menu.addAction(pin_act)
            terms = self._running_terminals_for_workspace(ws.id)
            if terms:
                menu.addSeparator()
                count = len(terms)
                label = (
                    "▶ Continuar todos os consoles deste workspace"
                    if count > 1
                    else "▶ Continuar o console deste workspace"
                )
                continue_all_act = QAction(label, menu)
                continue_all_act.setToolTip(
                    f"Manda 'continue' pra {count} console(s) Claude rodando neste workspace"
                )
                continue_all_act.triggered.connect(
                    lambda _c=False, ts=terms: [t.send_continue() for t in ts]
                )
                menu.addAction(continue_all_act)
        else:
            return
        if menu.isEmpty():
            return
        menu.exec_(self.list_widget.viewport().mapToGlobal(pos))

    def _add_session_info_actions(self, menu: QMenu, term: "TerminalWidget") -> None:
        """Prefixa o menu de contexto do console com infos da sessão Claude:
        modelo da última mensagem assistant + tokens acumulados + custo
        aproximado. Lê o JSONL claimed; se sessão ainda não resolveu,
        mostra placeholder informativo."""
        from ..usage_telemetry import format_tokens, usage_for_session

        path = term.claimed_session_path()
        if path is None:
            placeholder = QAction("(sessão ainda não resolvida)", menu)
            placeholder.setEnabled(False)
            menu.addAction(placeholder)
            menu.addSeparator()
            return
        try:
            stats = usage_for_session(path)
        except Exception:  # noqa: BLE001
            log.debug("falha ao agregar usage da sessão %s", path, exc_info=True)
            return
        model_label = stats.last_model or "(modelo desconhecido)"
        model_act = QAction(f"✦ Modelo: {model_label}", menu)
        model_act.setEnabled(False)
        menu.addAction(model_act)
        if stats.total_tokens > 0:
            tokens_label = (
                f"⌬ Tokens: {format_tokens(stats.input_tokens)} in · "
                f"{format_tokens(stats.output_tokens)} out · "
                f"{format_tokens(stats.cache_creation_tokens + stats.cache_read_tokens)} cache"
            )
            tokens_act = QAction(tokens_label, menu)
            tokens_act.setEnabled(False)
            menu.addAction(tokens_act)
        if stats.cost_usd > 0:
            cost_act = QAction(f"$ Custo aprox.: ~${stats.cost_usd:.2f}", menu)
            cost_act.setEnabled(False)
            menu.addAction(cost_act)
        menu.addSeparator()

    def _running_terminals_for_workspace(self, workspace_id: str) -> list[TerminalWidget]:
        area = self.terminals_coord.area_for(workspace_id)
        if area is None:
            return []
        out: list[TerminalWidget] = []
        for i in range(area.tabs.count()):
            w = area.tabs.widget(i)
            if isinstance(w, TerminalWidget) and w.is_running():
                out.append(w)
        return out

    def _show_release_notes(self) -> None:
        from .release_notes_dialog import ReleaseNotesDialog

        dlg = ReleaseNotesDialog(parent=self)
        dlg.exec()

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
        self._runner_tree_items.clear()
        self._runner_group_items.clear()
        self._console_runner_group_items.clear()

        from PySide6.QtGui import QFont

        ws_font = QFont(self.list_widget.font())
        ws_font.setBold(True)

        # Particiona: workspaces fixados aparecem em "FIXADOS" no topo,
        # fora da lista principal (não duplica).
        pinned = [ws for ws in self.workspaces if ws.pinned]
        regular = [ws for ws in self.workspaces if not ws.pinned]

        def _add_workspace(ws: Workspace) -> None:
            item = QTreeWidgetItem([""])
            item.setData(0, Qt.ItemDataRole.UserRole, ws)
            item.setFont(0, ws_font)
            tip = ws.description or ""
            if ws.folders:
                tip = (tip + "\n\n" if tip else "") + "\n".join(ws.folders)
            if tip:
                item.setToolTip(0, tip)
            self.list_widget.addTopLevelItem(item)
            # Restaura estado colapsado persistido (default = expandido).
            collapsed = bool(self.settings.workspace_collapsed.get(ws.id, False))
            item.setExpanded(not collapsed)
            self._install_workspace_item_widget(item, ws)

        if pinned:
            self._add_section_header("FIXADOS")
            for ws in pinned:
                _add_workspace(ws)
            self._add_section_header("WORKSPACES")
        for ws in regular:
            _add_workspace(ws)

        self._apply_filter(
            self.top_bar.search.text() if hasattr(self, "top_bar") else ""
        )
        self._refresh_activity_badges()

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

        # Footer: runners por workspace (workspace-scope), sempre ao final
        # dos children. Runners console-scope são anexados pelo
        # `_add_terminal_child` quando o console entra na sidebar; aqui
        # re-anexa pros consoles já existentes na re-listagem.
        for i in range(self.list_widget.topLevelItemCount()):
            it = self.list_widget.topLevelItem(i)
            ws_data = it.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(ws_data, Workspace):
                self._install_runner_children(it, ws_data)
                for j in range(it.childCount()):
                    sib = it.child(j)
                    tab_id = sib.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(tab_id, int):
                        self._install_console_runner_children(sib, ws_data, tab_id)
                self._refresh_empty_placeholder(it)

        if current_id:
            ws_item = self._find_workspace_item(current_id)
            if ws_item is not None and not ws_item.isHidden():
                self.list_widget.setCurrentItem(ws_item)
                return

        for i in range(self.list_widget.topLevelItemCount()):
            it = self.list_widget.topLevelItem(i)
            if not it.isHidden() and not self._is_section_header(it):
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
        # O indicador de "rodando" (bolinha verde + badge) é renderizado
        # pelo WorkspaceItemWidget — aqui só o nome.
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
                if not it.isHidden() and not self._is_section_header(it):
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
        self.list_widget.setCurrentItem(self.list_widget.topLevelItem(rows[0]))
        self.list_widget.setFocus()

    def _refresh_item_label(self, workspace_id: str) -> None:
        item = self._find_workspace_item(workspace_id)
        if item is None:
            return
        ws = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(ws, Workspace):
            return
        widget = self.list_widget.itemWidget(item, 0)
        from .workspace_item_widget import WorkspaceItemWidget
        count = self.terminals_coord.state.running_counts.get(ws.id, 0)
        if isinstance(widget, WorkspaceItemWidget):
            widget.set_label(ws.name)
            widget.set_running_count(count)
        else:
            item.setText(0, self._item_label(ws))

    _SECTION_HEADER_ROLE = "__section_header__"

    def _add_section_header(self, label: str) -> None:
        """Insere um item-cabeçalho não-selecionável (FIXADOS / WORKSPACES)."""
        item = QTreeWidgetItem([""])
        item.setData(0, Qt.ItemDataRole.UserRole, self._SECTION_HEADER_ROLE)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list_widget.addTopLevelItem(item)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "QLabel { color: #707070; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1.4px; padding: 8px 4px 4px 4px; }"
        )
        self.list_widget.setItemWidget(item, 0, lbl)

    def _is_section_header(self, item: "QTreeWidgetItem | None") -> bool:
        if item is None:
            return False
        return item.data(0, Qt.ItemDataRole.UserRole) == self._SECTION_HEADER_ROLE

    def _install_workspace_item_widget(
        self, item: "QTreeWidgetItem", ws: Workspace
    ) -> None:
        """Coloca um WorkspaceItemWidget no item do workspace, com os
        botões + (abrir Claude) e ▾/▸ (colapsar/expandir)."""
        from .workspace_item_widget import WorkspaceItemWidget

        def on_add() -> None:
            # Garante que o workspace alvo do + vire o selecionado — sem
            # isso, o painel de detalhes/abas continua no projeto antigo
            # mesmo com o console novo sendo aberto neste workspace.
            self.list_widget.setCurrentItem(item)
            self._launch_claude_for(ws, "", "")

        def on_toggle() -> None:
            item.setExpanded(not item.isExpanded())
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, WorkspaceItemWidget):
                widget.set_collapsed(not item.isExpanded())

        widget = WorkspaceItemWidget(ws.name, on_add, on_toggle)
        widget.set_collapsed(not item.isExpanded())
        widget.set_running_count(
            self.terminals_coord.state.running_counts.get(ws.id, 0)
        )
        self.list_widget.setItemWidget(item, 0, widget)
        self._refresh_empty_placeholder(item)

    _EMPTY_PLACEHOLDER_ROLE = "__empty_workspace_placeholder__"

    def _refresh_empty_placeholder(self, ws_item: "QTreeWidgetItem") -> None:
        """Garante 1 placeholder com botão 'Nova sessão do claude…' quando o
        workspace não tem nenhum filho real (consoles/runners). Remove
        quando passa a ter qualquer filho. Idempotente, seguro chamar
        após cada add/remove de child."""
        from PySide6.QtWidgets import QPushButton

        ws = ws_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(ws, Workspace):
            return

        placeholder_idx = -1
        real_count = 0
        for i in range(ws_item.childCount()):
            child = ws_item.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == self._EMPTY_PLACEHOLDER_ROLE:
                placeholder_idx = i
            else:
                real_count += 1

        if real_count > 0:
            if placeholder_idx >= 0:
                ws_item.takeChild(placeholder_idx)
            return

        if placeholder_idx >= 0:
            return  # já existe

        child = QTreeWidgetItem()
        child.setData(0, Qt.ItemDataRole.UserRole, self._EMPTY_PLACEHOLDER_ROLE)
        child.setSizeHint(0, QSize(0, 30))
        btn = QPushButton("＋  Nova sessão do claude…")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(24)
        btn.setToolTip(
            "Abre um Claude novo neste workspace (mesma ação do botão + "
            "ao lado do nome)"
        )
        btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9aa0a6; "
            "border: 1px dashed #3a3a3a; border-radius: 4px; "
            "padding: 4px 8px; margin: 0px; text-align: left; "
            "font-size: 11px; }"
            "QPushButton:hover { color: #e6e6e6; border-color: #5a5a5a; "
            "background: #1f1f1f; }"
        )
        btn.clicked.connect(lambda: self._launch_claude_for(ws, "", ""))
        ws_item.addChild(child)
        self.list_widget.setItemWidget(child, 0, btn)

    def _install_runner_children(
        self, ws_item: "QTreeWidgetItem", ws: Workspace
    ) -> None:
        """Cria/atualiza as linhas de runner ("footer") embaixo do
        workspace na sidebar, agrupadas sob um header colapsável
        "Runners workspace". Cobre apenas runners de escopo workspace
        (sem console_session_id). Os de console ficam como filhos do
        próprio item do console — ver `_install_console_runner_children`.
        """
        from .runner_child_widget import RunnerChildWidget
        from .runner_group_widget import RunnerGroupWidget

        # Remove rows antigos de runners workspace-scope (estavam sob o
        # group item antigo, se existia; ou direto sob ws_item em versões
        # anteriores). Limpa nos dois lugares pra ser idempotente.
        existing = self._runner_tree_items.get(ws.id, {})
        group_old = self._runner_group_items.get(ws.id)
        for rid, item in list(existing.items()):
            parent = item.parent()
            if parent is ws_item or (group_old is not None and parent is group_old):
                parent.removeChild(item)
                self._runner_tree_items[ws.id].pop(rid, None)

        scoped = [r for r in ws.runners if not (r.console_session_id or "")]
        if not scoped:
            # Sem runners workspace-scope → remove o header se existia.
            if group_old is not None:
                ws_item.removeChild(group_old)
                self._runner_group_items.pop(ws.id, None)
            return

        # Garante o header "Runners workspace" como filho do ws_item,
        # sempre no topo — antes da lista de consoles.
        group = self._runner_group_items.get(ws.id)
        if group is None:
            group = QTreeWidgetItem()
            group.setData(0, Qt.ItemDataRole.UserRole, ("runner_group", ws.id, ""))
            group.setSizeHint(0, QSize(0, 24))
            ws_item.insertChild(0, group)

            def _toggle(*_, g=group):
                g.setExpanded(not g.isExpanded())
                w = self.list_widget.itemWidget(g, 0)
                if isinstance(w, RunnerGroupWidget):
                    w.set_collapsed(not g.isExpanded())

            header = RunnerGroupWidget(
                "Runners workspace",
                on_add_blank=lambda w=ws: self._open_runner_edit(w, None),
                on_generate=lambda w=ws: self._generate_runner_with_claude(w),
                on_toggle_collapse=_toggle,
                on_stop_all=lambda _c=False, w=ws: self._stop_all_workspace_runners(w),
                on_restart_all=lambda _c=False, w=ws: self._restart_all_workspace_runners(w),
            )
            self.list_widget.setItemWidget(group, 0, header)
            collapsed = bool(
                self.settings.runner_group_collapsed.get(ws.id, False)
            )
            group.setExpanded(not collapsed)
            header.set_collapsed(collapsed)
            self._runner_group_items[ws.id] = group

        self._runner_tree_items.setdefault(ws.id, {})
        for runner in scoped:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, ("runner", ws.id, runner.id))
            child.setSizeHint(0, QSize(0, 24))
            widget = RunnerChildWidget(
                runner.name or "(runner)",
                lambda rid=runner.id, wid=ws.id: self._toggle_runner_from_sidebar(wid, rid),
            )
            area = self._runner_areas.get(ws.id)
            if area is not None:
                rw = area.widget_for(runner.id)
                if rw is not None:
                    widget.set_state(rw.current_state())
                    widget.set_url(rw.current_url())
                    widget.set_status(rw.current_status_label())
                    child.setSizeHint(0, QSize(0, widget.preferred_height() + 2))
            else:
                # Sem RunnerArea instanciada ainda → usa o browser_url da
                # config como fallback (URL detectada precisa do runtime).
                widget.set_url(runner.browser_url or "")
            group.addChild(child)
            self.list_widget.setItemWidget(child, 0, widget)
            self._runner_tree_items[ws.id][runner.id] = child

    def _install_console_runner_children(
        self, term_item: "QTreeWidgetItem", ws: Workspace, tab_id: int
    ) -> None:
        """Cria/atualiza os runner-children como filhos do item do console,
        agrupados sob um header colapsável "Runners console". Filtra pelo
        `console_session_id` resolvido do terminal (ou pela chave pendente
        quando o session_id ainda não chegou)."""
        from .runner_child_widget import RunnerChildWidget
        from .runner_group_widget import RunnerGroupWidget

        gk = (ws.id, tab_id)
        group_old = self._console_runner_group_items.get(gk)

        # Remove rows antigos vinculados a esse console (sob term_item ou
        # sob o group_old). Preserva os de outros consoles e workspace-scope.
        existing = self._runner_tree_items.get(ws.id, {})
        for rid, item in list(existing.items()):
            parent = item.parent()
            if parent is term_item or (group_old is not None and parent is group_old):
                parent.removeChild(item)
                self._runner_tree_items[ws.id].pop(rid, None)

        term = self._terminal_widget_for(tab_id)
        if term is None:
            if group_old is not None:
                term_item.removeChild(group_old)
                self._console_runner_group_items.pop(gk, None)
            return
        # Fonte da verdade: se a RunnerArea do console já existe, usamos
        # exatamente os runners que ela mostra (mesmo escopo aplicado lá).
        # Senão, filtra por sid do terminal (claim/pending).
        existing_area = self._console_runner_areas.get(ws.id, {}).get(tab_id)
        if existing_area is not None:
            scoped = existing_area.runners_in_scope()
        else:
            sid = term.claimed_session_id() or self._pending_console_key(term)
            scoped = [r for r in ws.runners if (r.console_session_id or "") == sid]
        if not scoped:
            if group_old is not None:
                term_item.removeChild(group_old)
                self._console_runner_group_items.pop(gk, None)
            return

        # Header "Runners console" como filho do term_item.
        group = self._console_runner_group_items.get(gk)
        if group is None:
            group = QTreeWidgetItem()
            group.setData(
                0,
                Qt.ItemDataRole.UserRole,
                ("runner_group", ws.id, f"console:{tab_id}"),
            )
            group.setSizeHint(0, QSize(0, 24))
            term_item.addChild(group)

            def _add_blank(w=ws, t=term):
                area = self._ensure_terminal_runner_panel(w, t)
                self._open_runner_edit(
                    w, None, console_session_id=area.console_session_id()
                )

            def _gen(w=ws):
                self._generate_runner_with_claude(w)

            def _toggle(*_, g=group):
                g.setExpanded(not g.isExpanded())
                w = self.list_widget.itemWidget(g, 0)
                if isinstance(w, RunnerGroupWidget):
                    w.set_collapsed(not g.isExpanded())

            header = RunnerGroupWidget(
                "Runners console",
                on_add_blank=_add_blank,
                on_generate=_gen,
                on_toggle_collapse=_toggle,
                on_stop_all=lambda _c=False, w=ws, t=term: self._stop_all_console_runners(w, t),
                on_restart_all=lambda _c=False, w=ws, t=term: self._restart_all_console_runners(w, t),
            )
            self.list_widget.setItemWidget(group, 0, header)
            group.setExpanded(True)
            header.set_collapsed(False)
            self._console_runner_group_items[gk] = group

        self._runner_tree_items.setdefault(ws.id, {})
        for runner in scoped:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, ("runner", ws.id, runner.id))
            child.setSizeHint(0, QSize(0, 24))
            widget = RunnerChildWidget(
                runner.name or "(runner)",
                lambda rid=runner.id, wid=ws.id: self._toggle_runner_from_sidebar(wid, rid),
            )
            # Estado inicial: runners de console ficam em _console_runner_areas.
            url_set = False
            for carea in self._console_runner_areas.get(ws.id, {}).values():
                rw = carea.widget_for(runner.id)
                if rw is not None:
                    widget.set_state(rw.current_state())
                    widget.set_url(rw.current_url())
                    widget.set_status(rw.current_status_label())
                    child.setSizeHint(0, QSize(0, widget.preferred_height() + 2))
                    url_set = True
                    break
            if not url_set:
                widget.set_url(runner.browser_url or "")
            group.addChild(child)
            self.list_widget.setItemWidget(child, 0, widget)
            self._runner_tree_items[ws.id][runner.id] = child
        # Tem runners no console — expande o item pro grupo ficar visível.
        # Sem isso o grupo era criado mas ficava escondido dentro do item
        # de console colapsado, dando a impressão de "não tem runners".
        term_item.setExpanded(True)

    def _toggle_runner_from_sidebar(self, workspace_id: str, runner_id: str) -> None:
        """Inicia/para um runner pela sidebar. Cria a RunnerArea sob
        demanda (lazy) — necessário pra workspaces nunca abertos. Tenta
        primeiro o painel do workspace; depois cai pros painéis de console
        (runners scoped a um session_id moram em outra RunnerArea)."""
        ws = self.workspaces_coord.find_by_id(workspace_id)
        if ws is None:
            return
        rw = None
        area = self._get_or_create_runner_area(ws)
        if area is not None:
            rw = area.widget_for(runner_id)
        if rw is None:
            for carea in self._console_runner_areas.get(workspace_id, {}).values():
                rw = carea.widget_for(runner_id)
                if rw is not None:
                    break
        if rw is None:
            return
        if rw.is_running():
            rw.stop()
        else:
            rw.start()

    def _refresh_runner_children(self, workspace_id: str) -> None:
        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is None:
            return
        ws = ws_item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(ws, Workspace):
            return
        self._install_runner_children(ws_item, ws)
        # Cada console também tem seus runners — refaz para todos.
        for i in range(ws_item.childCount()):
            sib = ws_item.child(i)
            tab_id = sib.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(tab_id, int):
                self._install_console_runner_children(sib, ws, tab_id)

    def _on_runner_state_changed(
        self, workspace_id: str, runner_id: str, state: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_state(state)

    def _on_runner_status_changed(
        self, workspace_id: str, runner_id: str, status: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_status(status)
            item.setSizeHint(0, QSize(0, widget.preferred_height() + 2))

    def _on_runner_url_changed(
        self, workspace_id: str, runner_id: str, url: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_url(url)

    def _on_workspace_running(self, workspace_id: str, count: int) -> None:
        if count <= 0:
            self.terminals_coord.state.running_counts.pop(workspace_id, None)
        else:
            self.terminals_coord.state.running_counts[workspace_id] = count
        self._refresh_item_label(workspace_id)
        self._refresh_activity_badges()

    def _refresh_activity_badges(self) -> None:
        """Atualiza os contadores do ActivityBar (workspaces + apps).

        Workspaces: "trabalhando/total" — quantos têm runtime Claude
        ativo vs total cadastrado. Apps: total de PWAs configurados.
        """
        if not hasattr(self, "activity_bar"):
            return
        total = len(self.workspaces_coord.workspaces)
        working = sum(
            1
            for ws in self.workspaces_coord.workspaces
            if self.terminals_coord.state.running_counts.get(ws.id, 0) > 0
        )
        if total > 0:
            badge = f"{working}/{total}" if working > 0 else str(total)
            tip = (
                f"{working} trabalhando · {total - working} ocioso(s) · "
                f"{total} no total"
            )
            self.activity_bar.set_badge(VIEW_WORKSPACES, badge, tip)
        else:
            self.activity_bar.set_badge(VIEW_WORKSPACES, "")

        apps = len(self.settings.apps or [])
        if apps > 0:
            self.activity_bar.set_badge(
                VIEW_APPS, str(apps), f"{apps} app(s) auxiliar(es) configurado(s)"
            )
        else:
            self.activity_bar.set_badge(VIEW_APPS, "")

    # ---------- seleção / settings ----------

    def _on_selection_changed(self, current, _previous) -> None:
        # Atualiza a barra branca de seleção dos consoles: zera a do
        # item anterior, liga a do novo. Só TerminalChildWidget tem
        # `set_selected`; outros widgets (workspace header, runner)
        # ignoram.
        for item in (_previous, current):
            if item is None:
                continue
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, TerminalChildWidget):
                widget.set_selected(item is current)

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
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        # Clique num runner-child → abre o console/log daquele runner.
        if isinstance(data, tuple) and len(data) == 3 and data[0] == "runner":
            ws = self.workspaces_coord.find_by_id(data[1])
            if ws is not None:
                self._open_runner_from_sidebar(ws, data[2])
            return
        if not isinstance(data, int):  # só tab_id de aba viva
            return
        pdata = item.parent().data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(pdata, Workspace):
            return
        self._focus_terminal_tab(pdata, data)

    def _on_tree_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        # Double-click ou Enter numa aba viva foca a aba existente.
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        pdata = item.parent().data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(pdata, Workspace):
            return
        # Linha de runner ("footer") → abre aba Runners + foca o runner
        if (
            isinstance(data, tuple)
            and len(data) == 3
            and data[0] == "runner"
        ):
            self._open_runner_from_sidebar(pdata, data[2])
            return
        if not isinstance(data, int):  # tab_id
            return
        self._focus_terminal_tab(pdata, data)

    def _open_runner_from_sidebar(self, workspace: Workspace, runner_id: str) -> None:
        """Switch pro bottom tab "Runners" e foca a aba do runner.

        Resolve o escopo automaticamente: runners workspace-scope abrem
        no painel "Runners workspace"; runners de console abrem no painel
        "Runners (console)" do console dono."""
        # Identifica o escopo procurando o runner no workspace.
        runner = next((r for r in workspace.runners if r.id == runner_id), None)
        sid = (runner.console_session_id or "") if runner is not None else ""
        if sid:
            # Console-scope: localiza a RunnerArea do console dono.
            for area in self._console_runner_areas.get(workspace.id, {}).values():
                if area.console_session_id() == sid:
                    self.console_runner_host.setCurrentWidget(area)
                    self._bottom_tabs.setCurrentWidget(self.console_runner_host)
                    area.focus_runner(runner_id)
                    return
            # Área ainda não criada → garante criando via terminal dono.
            for tab_id, term_item in self.terminals_coord.state.tree_items.items():
                term = self._terminal_widget_for(tab_id)
                if term is None:
                    continue
                term_sid = term.claimed_session_id() or self._pending_console_key(term)
                if term_sid == sid:
                    area = self._ensure_terminal_runner_panel(workspace, term)
                    area.focus_runner(runner_id)
                    return
            # Não achou console dono (foi encerrado?) — fallback pro workspace.
        area = self._get_or_create_runner_area(workspace)
        self.runner_host.setCurrentWidget(area)
        self._bottom_tabs.setCurrentWidget(self.runner_host)
        area.focus_runner(runner_id)

    def _focus_terminal_tab(self, workspace: Workspace, tab_id: int) -> None:
        area = self.terminals_coord._areas.get(workspace.id)
        if area is None:
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                self._bottom_tabs.setCurrentWidget(self.terminal_host)
                break

    def _show_settings(self) -> None:
        # Garante que estamos na view de workspaces (settings vive no
        # content_stack interno do body_splitter)
        self.main_stack.setCurrentWidget(self.body_view)
        self.activity_bar.set_active(VIEW_SETTINGS)
        self.content_stack.setCurrentWidget(self._settings_scroll)

    def _show_workspaces(self) -> None:
        self.main_stack.setCurrentWidget(self.body_view)
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
        # Runner area é lazy — cria quando o workspace é selecionado pela
        # primeira vez. Garante widgets pra runners persistidos mesmo antes
        # de o usuário abrir a aba "Runners".
        runner_area = self._get_or_create_runner_area(workspace)
        self.runner_host.setCurrentWidget(runner_area)
        self._sync_console_runner_host()
        # Re-instala os runner-children dos consoles desse workspace —
        # cobre o caso de o `claimed_session_id` do terminal ter sido
        # resolvido depois da primeira instalação (signal não chegou ou
        # o JSONL só apareceu mais tarde).
        self._refresh_runner_children(workspace.id)

    def _sync_console_runner_host(self) -> None:
        """Mostra na aba 'Runners (console)' o painel do console ativo
        (terminal atualmente focado). Cai pro placeholder se nenhum
        console tiver painel ainda criado."""
        area = self._active_terminal_area()
        target = None
        if area is not None:
            term = area.tabs.currentWidget()
            if term is not None:
                ws_id = None
                for wid, a in self.terminals_coord._areas.items():
                    if a is area:
                        ws_id = wid
                        break
                if ws_id is not None:
                    target = self._console_runner_areas.get(ws_id, {}).get(
                        id(term)
                    )
        if target is not None:
            self.console_runner_host.setCurrentWidget(target)
        else:
            self.console_runner_host.setCurrentIndex(
                self._console_runner_placeholder_idx
            )

    def _get_or_create_runner_area(self, workspace: Workspace) -> RunnerArea:
        area = self._runner_areas.get(workspace.id)
        if area is not None:
            return area
        area = RunnerArea(workspace, settings=self.settings)
        self._runner_areas[workspace.id] = area
        self.runner_host.addWidget(area)
        ws = workspace
        area.set_edit_handler(
            lambda runner, w=ws: self._open_runner_edit(w, runner)
        )
        area.set_generate_handler(
            lambda w=ws: self._generate_runner_with_claude(w)
        )
        area.runners_changed.connect(lambda w=ws: self._persist_workspace(w))
        area.runners_changed.connect(
            lambda wid=ws.id: self._refresh_runner_children(wid)
        )
        area.running_count_changed.connect(
            lambda count, wid=ws.id: self._on_runner_running(wid, count)
        )
        area.runner_state_changed.connect(
            lambda rid, state, wid=ws.id: self._on_runner_state_changed(wid, rid, state)
        )
        area.runner_url_changed.connect(
            lambda rid, url, wid=ws.id: self._on_runner_url_changed(wid, rid, url)
        )
        area.runner_status_changed.connect(
            lambda rid, txt, wid=ws.id: self._on_runner_status_changed(wid, rid, txt)
        )
        return area

    # ---- bulk actions disparadas pelo header da sidebar ------------------

    def _stop_all_workspace_runners(self, workspace: Workspace) -> None:
        area = self._runner_areas.get(workspace.id)
        if area is None:
            return
        area.stop_all()

    def _restart_all_workspace_runners(self, workspace: Workspace) -> None:
        # Garante a RunnerArea pra cobrir o caso de o usuário clicar
        # "↻" no header sem ter aberto a aba de runners ainda.
        area = self._get_or_create_runner_area(workspace)
        area.restart_all()

    def _stop_all_console_runners(self, workspace: Workspace, terminal) -> None:
        area = self._console_runner_areas.get(workspace.id, {}).get(id(terminal))
        if area is None:
            return
        area.stop_all()

    def _restart_all_console_runners(self, workspace: Workspace, terminal) -> None:
        area = self._ensure_terminal_runner_panel(workspace, terminal)
        area.restart_all()

    def _open_runner_edit(
        self, workspace, runner, console_session_id: str = ""
    ) -> None:
        dlg = RunnerEditDialog(
            runner,
            on_generate_with_claude=lambda: self._generate_runner_with_claude(
                workspace
            ),
            on_resume_gen=lambda sid, cwd, w=workspace:
                self._resume_runner_gen_session(w, sid, cwd),
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        new_cfg = dlg.result_runner()
        if runner is None:
            # Stampa o escopo do painel que originou o "+ Novo".
            new_cfg.console_session_id = console_session_id
            workspace.runners.append(new_cfg)
        else:
            for i, r in enumerate(workspace.runners):
                if r.id == new_cfg.id:
                    # Preserva o escopo do runner existente — edição não muda.
                    new_cfg.console_session_id = r.console_session_id
                    workspace.runners[i] = new_cfg
                    break
        self._persist_workspace(workspace)
        # Refresh em todas as áreas que possam mostrar este runner.
        area = self._runner_areas.get(workspace.id)
        if area is not None:
            area.refresh()
        for area in self._console_runner_areas.get(workspace.id, {}).values():
            area.refresh()

    def _pending_console_key(self, terminal) -> str:
        """Chave temporária pro escopo de um console enquanto o session_id
        do Claude ainda não foi resolvido. Permite criar runners de console
        em sessões novas (que só ganham id depois do primeiro flush do
        JSONL). Quando o id real chega, `_on_terminal_session_id_changed`
        re-stampa todos os runners com essa chave."""
        return f"pending:{id(terminal):x}"

    def _wire_terminal_runner_panel(self, workspace: Workspace, terminal) -> None:
        terminal.runner_panel_toggle_requested.connect(
            lambda w=workspace, t=terminal:
                self._ensure_terminal_runner_panel(w, t)
        )
        terminal.claimed_session_id_changed.connect(
            lambda sid, w=workspace, t=terminal:
                self._on_terminal_session_id_changed(w, t, sid)
        )

    def _ensure_terminal_runner_panel(self, workspace: Workspace, terminal) -> RunnerArea:
        existing = self._console_runner_areas.get(workspace.id, {}).get(id(terminal))
        if existing is not None:
            # Já existe — só foca a aba "Runners (console)" no painel certo.
            self.console_runner_host.setCurrentWidget(existing)
            self._bottom_tabs.setCurrentWidget(self.console_runner_host)
            return existing
        sid = terminal.claimed_session_id() or self._pending_console_key(terminal)
        area = RunnerArea(workspace, settings=self.settings, console_session_id=sid)
        area.set_edit_handler(
            lambda runner, w=workspace, a=area:
                self._open_runner_edit(w, runner, console_session_id=a.console_session_id())
        )
        area.set_generate_handler(
            lambda w=workspace: self._generate_runner_with_claude(w)
        )
        area.runners_changed.connect(lambda w=workspace: self._persist_workspace(w))
        area.runners_changed.connect(
            lambda wid=workspace.id: self._refresh_runner_children(wid)
        )
        area.runner_state_changed.connect(
            lambda rid, state, wid=workspace.id:
                self._on_runner_state_changed(wid, rid, state)
        )
        area.runner_url_changed.connect(
            lambda rid, url, wid=workspace.id:
                self._on_runner_url_changed(wid, rid, url)
        )
        area.runner_status_changed.connect(
            lambda rid, txt, wid=workspace.id:
                self._on_runner_status_changed(wid, rid, txt)
        )
        self._console_runner_areas.setdefault(workspace.id, {})[id(terminal)] = area
        # Painel mora no top tab "Runners (console)" — não embute mais no
        # próprio terminal. O toolbar `▤ Runners` do terminal só foca a aba.
        self.console_runner_host.addWidget(area)
        self.console_runner_host.setCurrentWidget(area)
        self._bottom_tabs.setCurrentWidget(self.console_runner_host)
        # Atualiza o grupo "Runners console" da sidebar — agora que a
        # area existe, o lookup pelo `_console_runner_areas` casa o sid
        # com os runners persistidos (chave pending criada no boot
        # antes de o session_id ter sido reportado).
        term_item = self.terminals_coord.state.tree_items.get(id(terminal))
        if term_item is not None:
            self._install_console_runner_children(
                term_item, workspace, id(terminal)
            )
        return area

    def _on_terminal_session_id_changed(
        self, workspace: Workspace, terminal, sid: str
    ) -> None:
        areas = self._console_runner_areas.get(workspace.id, {})
        area = areas.get(id(terminal))
        if area is None:
            return
        old = area.console_session_id()
        if old == sid or not sid:
            return
        # Re-stampa runners que estavam usando a chave temporária pra apontar
        # pro session_id real. Sem isso, ao reiniciar o app os runners ficariam
        # órfãos (chave temporária baseada em id(widget) muda a cada execução).
        if old.startswith("pending:"):
            changed = False
            for r in workspace.runners:
                if (r.console_session_id or "") == old:
                    r.console_session_id = sid
                    changed = True
            if changed:
                self._persist_workspace(workspace)
        area.set_console_session_id(sid)
        # Re-anexa runner children do console na sidebar usando o sid novo.
        tab_id = id(terminal)
        term_item = self.terminals_coord.state.tree_items.get(tab_id)
        if term_item is not None:
            self._install_console_runner_children(term_item, workspace, tab_id)

    def _generate_runner_with_claude(self, workspace) -> None:
        from ..launchers import find_app_repo_root
        from ..services.runner_gen_history import RunnerGenEntry, add_entry
        from ..services.runner_prompt import build_generate_prompt
        from .runner_gen_dialog import RunnerGenDialog

        dlg = RunnerGenDialog(workspace.id, workspace.name, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        mode = dlg.mode()

        repo = find_app_repo_root()
        if repo is None:
            QMessageBox.warning(
                self,
                "Não foi possível abrir o Claude",
                "Repositório do claude-workspaces não encontrado — gerador "
                "precisa rodar no diretório do projeto pra ler docs/runners-spec.md",
            )
            return

        if not workspace.folders:
            QMessageBox.warning(
                self,
                "Workspace sem pastas",
                "Adicione ao menos uma pasta no workspace antes de gerar runner.",
            )
            return

        area = self.terminals_coord.get_or_create_area(workspace)
        ws_cwd, extras = workspace.launch_paths()

        if mode == "resume":
            entry = dlg.selected_entry()
            if entry is None:
                return
            argv = [
                self.settings.claude_command,
                *self.settings.claude_extra_args,
                "--resume",
                entry.session_id,
            ]
            # Re-anexa --add-dir igual à geração nova pra Claude ainda ler o spec
            # e enxergar pastas extras.
            argv += ["--add-dir", str(repo)]
            for extra in extras:
                argv += ["--add-dir", extra]
            title = f"runner-gen #{area.count() + 1} (resume)"
            terminal = area.add_terminal(title)
            terminal.configure_claude(entry.cwd, resume_id=entry.session_id)
            label = f"claude (runner-gen resume) — {workspace.name}"
            cwd = entry.cwd
        else:
            hint = dlg.hint()
            spec_path = Path(repo) / "docs" / "runners-spec.md"
            prompt = build_generate_prompt(workspace, hint, spec_path=spec_path)
            # NÃO usar --add-dir aqui: Claude CLI 2.1.x descarta o prompt
            # posicional silenciosamente quando --add-dir está presente.
            # Como passamos --dangerously-skip-permissions (extra_args), o
            # claude consegue ler os paths absolutos do spec e das pastas
            # extras via Read sem precisar de --add-dir.
            argv = [
                self.settings.claude_command,
                *self.settings.claude_extra_args,
                prompt,
            ]
            title = f"runner-gen #{area.count() + 1}"
            terminal = area.add_terminal(title)
            terminal.configure_claude(ws_cwd)
            label = f"claude (runner-gen) — {workspace.name}"
            cwd = ws_cwd

            ws_id = workspace.id

            def _record_once(sid: str, *, _t=terminal, _cwd=cwd, _ws=ws_id, _hint=hint) -> None:
                if not sid:
                    return
                try:
                    add_entry(RunnerGenEntry(
                        workspace_id=_ws, session_id=sid, cwd=_cwd, hint=_hint,
                    ))
                except Exception:
                    log.exception("Falha ao registrar runner-gen no histórico")
                try:
                    _t.claimed_session_id_changed.disconnect(_record_once)
                except (TypeError, RuntimeError):
                    pass

            terminal.claimed_session_id_changed.connect(_record_once)

        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=label,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            QMessageBox.warning(self, "Não foi possível abrir o Claude", str(e))
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

    def _resume_runner_gen_session(self, workspace, session_id: str, cwd: str) -> None:
        """Reabre uma sessão Claude de runner-gen via `--resume`.

        Usado pelo dialog de edição (botão "Retomar geração com Claude")
        e pode ser reusado por outros pontos. O JSONL precisa existir em
        `~/.claude/projects/<encoded(cwd)>/<session_id>.jsonl`.
        """
        from ..claude_sessions import project_sessions_dir
        from ..launchers import find_app_repo_root

        if not session_id or not cwd:
            QMessageBox.information(
                self,
                "Sessão indisponível",
                "Este runner não tem sessão de geração associada — "
                "foi criado manualmente ou antes desse recurso existir.",
            )
            return
        jsonl = project_sessions_dir(cwd) / f"{session_id}.jsonl"
        if not jsonl.exists():
            QMessageBox.warning(
                self,
                "Sessão não encontrada",
                f"O JSONL da sessão de geração não existe mais:\n{jsonl}",
            )
            return

        repo = find_app_repo_root()
        argv = [
            self.settings.claude_command,
            *self.settings.claude_extra_args,
            "--resume",
            session_id,
        ]
        if repo is not None:
            argv += ["--add-dir", str(repo)]
        if workspace.folders:
            _, extras = workspace.launch_paths()
            for extra in extras:
                argv += ["--add-dir", extra]

        area = self.terminals_coord.get_or_create_area(workspace)
        title = f"runner-gen #{area.count() + 1} (resume)"
        terminal = area.add_terminal(title)
        terminal.configure_claude(cwd, resume_id=session_id)
        label = f"claude (runner-gen resume) — {workspace.name}"
        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=label,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            QMessageBox.warning(self, "Não foi possível abrir o Claude", str(e))
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

    def _persist_workspace(self, workspace) -> None:
        self.workspaces_coord.replace(workspace)

    def _on_runner_running(self, workspace_id: str, count: int) -> None:
        if not hasattr(self, "_runner_running_counts"):
            self._runner_running_counts: dict[str, int] = {}
        if count <= 0:
            self._runner_running_counts.pop(workspace_id, None)
        else:
            self._runner_running_counts[workspace_id] = count
        self._refresh_item_label(workspace_id)

    def _get_terminal_area(self, workspace: Workspace) -> TerminalArea:
        """Compat: delega pro TerminalCoordinator."""
        return self.terminals_coord.get_or_create_area(workspace)

    def _on_area_created(self, workspace_id: str, area: TerminalArea) -> None:
        """TerminalCoordinator criou uma nova area — adiciona no host."""
        self.terminal_host.addWidget(area)
        # Trocar a aba ativa do workspace só re-sincroniza o runner host;
        # o % de plano não muda ao trocar de aba (cada chamada extra de
        # /api/oauth/usage gasta cota desnecessária do rate limit).
        area.tabs.currentChanged.connect(
            lambda _i: self._sync_console_runner_host()
        )

    def _handle_tab_activity(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
        workspace_id: str,
        needs_decision: bool = False,
    ) -> None:
        """Slot do TerminalCoordinator.tab_activity_changed.
        Atualiza o tree child. Inbox/spinner já foram tratados no coord."""
        self.plugin_coord.dispatch_session_event(
            tab_id, workspace_id, title, is_working, is_running, needs_decision
        )

        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is None:
            return
        if tab_id in self.terminals_coord.state.tree_items:
            self._update_terminal_child(
                tab_id, title, status, is_working, is_running, needs_decision
            )
        else:
            self._add_terminal_child(
                ws_item, tab_id, title, status, is_working, is_running, needs_decision
            )

    def _handle_tab_removed(self, tab_id: int) -> None:
        """Slot do TerminalCoordinator.tab_removed.
        Estado já foi limpo no coord; aqui só remove o item do tree."""
        self.plugin_coord.dispatch_tab_removed(tab_id)
        item = self.terminals_coord.state.tree_items.get(tab_id)
        parent_item = item.parent() if item is not None else None
        if item is not None and parent_item is not None:
            # Limpa as entradas de runner-children pendentes nesse console
            # do tracking dict (os QTreeWidgetItem são destruídos junto com
            # o parent removido, mas o dict ficaria com refs órfãs). Os
            # runners ficam sob o group "Runners console" → testamos parent
            # direto E avô.
            for ws_map in self._runner_tree_items.values():
                for rid, tree_item in list(ws_map.items()):
                    p = tree_item.parent()
                    if p is item or (p is not None and p.parent() is item):
                        ws_map.pop(rid, None)
            # Limpa o registry do group "Runners console" desse console.
            for gk in [
                k for k in self._console_runner_group_items.keys() if k[1] == tab_id
            ]:
                self._console_runner_group_items.pop(gk, None)
            parent_item.removeChild(item)
        self._tab_base_titles.pop(tab_id, None)
        # Aba que saiu pode ter sido a única causa de colisão — re-disambigua
        if parent_item is not None:
            self._refresh_workspace_child_titles(parent_item)
            # Se o workspace ficou sem nenhum console, restaura o placeholder
            # com botão "Nova sessão do claude…" pra dar uma ação visível.
            self._refresh_empty_placeholder(parent_item)
        # Limpa o RunnerArea do console fechado: agora o painel mora no
        # top tab "Runners (console)" (não mais embutido no terminal),
        # então é responsabilidade nossa remover do QStackedWidget.
        for areas in self._console_runner_areas.values():
            stale = areas.pop(tab_id, None)
            if stale is not None:
                self.console_runner_host.removeWidget(stale)
                stale.deleteLater()
        self._sync_console_runner_host()

    def _on_spinner_tick(self, spinner_char: str) -> None:
        """Slot do TerminalCoordinator.spinner_tick — atualiza children
        que estão working com o frame atual."""
        for tab_id, (status, working, title) in list(self.terminals_coord.state.activity.items()):
            if working:
                self._update_terminal_child(tab_id, title, status, True, True)

    def _on_idle_tick(self) -> None:
        """Tick de 1s — pede a cada TerminalChildWidget que reescreva seu
        label de estado, atualizando o cronômetro de ociosidade. Widgets
        que não estão idle ignoram a chamada."""
        for item in self.terminals_coord.state.tree_items.values():
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, TerminalChildWidget):
                widget.tick_idle()
                widget.tick_awaiting()

    def _on_settings_saved(self) -> None:
        """Re-aplica configs que afetam coordinators / tray ao salvar."""
        self.terminals_coord.set_reminder_interval(
            self.settings.notify_reminder_seconds,
            enabled=self.settings.notify_reminder_enabled,
        )
        TerminalWidget.set_idle_debounce_seconds(self.settings.idle_debounce_seconds)
        if self.settings.notify_native_enabled and self._tray is None:
            self._init_tray()
        elif not self.settings.notify_native_enabled and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
        elif self._tray is not None:
            self._tray.setToolTip(
                self.settings.notify_app_name or "Claude Workspaces"
            )
        # app_name é fixado no construtor do DesktopNotifier — recria pra
        # que a próxima notificação use o nome novo.
        if self._desktop_notifier is not None:
            self._desktop_notifier.deleteLater()
            self._desktop_notifier = None
        self._init_desktop_notifier()
        # Apps podem ter sido adicionados/removidos no settings → refresh badge.
        self._refresh_activity_badges()

    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray indisponível — toasts nativos desabilitados")
            return
        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(self.settings.notify_app_name or "Claude Workspaces")
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

    def _init_desktop_notifier(self) -> None:
        notifier = DesktopNotifier(
            app_name=self.settings.notify_app_name or "Claude Workspaces",
            parent=self,
        )
        if notifier.available and notifier.supports_actions:
            self._desktop_notifier = notifier
            # Escuta ações disparadas em QUALQUER notificação D-Bus (inclusive
            # as emitidas pelo notify-hook.py rodando em subprocess do Claude
            # Code). Filtramos por prefixo `open-console:` pra não colidir
            # com as actions internas do inbox alert ("open"/"snooze5"/"seen").
            notifier.action_invoked.connect(self._on_global_dbus_action)
            log.info("Notificador D-Bus com ações ativo (caps=%s)", notifier.capabilities)
        else:
            self._desktop_notifier = None
            log.info(
                "Notificador D-Bus indisponível (available=%s actions=%s) — "
                "caindo pro tray.showMessage",
                notifier.available, notifier.supports_actions,
            )

    def _on_inbox_alert(
        self, tab_id: int, info: dict, is_reminder: bool
    ) -> None:
        """Recebe alerta primário (working→idle) ou re-lembrete (timer).
        Tenta D-Bus com botões; cai pro tray.showMessage se indisponível."""
        if not self.settings.notify_native_enabled:
            return
        # Debounce do "Pronto": se o mesmo tab disparou working→idle nos
        # últimos 60s, suprime esse alerta. Console oscila com Claude
        # rodando hooks/sub-passos entre working↔idle várias vezes e o
        # usuário só quer ser avisado uma vez por turno. Reminders ignoram
        # o debounce — eles rodam num timer separado, são intencionais.
        import time
        if not is_reminder:
            last = self._ready_alert_last.get(tab_id, 0.0)
            now = time.monotonic()
            if now - last < 60.0:
                log.debug(
                    "inbox_alert 'Pronto' suprimido por debounce (tab=%s, age=%.1fs)",
                    tab_id, now - last,
                )
                return
            self._ready_alert_last[tab_id] = now
        ws = self.workspaces_coord.find_by_id(info.get("workspace_id", ""))
        ws_name = ws.name if ws else "Workspace"
        kind = info.get("kind", "ready")
        if is_reminder:
            title_prefix = self.settings.notify_reminder_prefix
        elif kind == "decision":
            title_prefix = self.settings.notify_decision_prefix
        else:
            title_prefix = self.settings.notify_ready_prefix
        title = f"{title_prefix} — {ws_name}" if title_prefix else ws_name
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
        workspace_id = info.get("workspace_id", "")
        # Toast in-app top-most (independente do KDE) — garante visibilidade
        # mesmo com Plasma matando o popup D-Bus. Notif do KDE continua
        # também, pra caso a janela esteja em outro virtual desktop.
        self._show_persistent_toast(tab_id, workspace_id, title, body)

        if self._desktop_notifier is not None:
            # Divisão de responsabilidades:
            # - Notif D-Bus: SEM action, SEM som, urgency=normal e timeout
            #   configurável (~10s) → aparece, fica visível um instante e
            #   some sozinha pra não ficar acumulando popup velho. Quem
            #   carrega a persistência é o toast in-app.
            # - Toast in-app (`_show_persistent_toast`): tem os botões
            #   (Abrir/Adiar/Já vi) + som + auto-dismiss com barra de
            #   progresso. Lifecycle 100% nosso.
            prev_nid = self._active_notifications.get(tab_id, 0)
            nid = self._desktop_notifier.notify(
                title=title,
                body=body,
                actions=[],
                timeout_ms=int(self.settings.notify_timeout_ms),
                replaces_id=prev_nid,
                urgency=1,
                desktop_entry="claude-workspaces",
                sound_name=None,
            )
            if nid is not None:
                self._active_notifications[tab_id] = nid
                return
            log.debug("D-Bus notify falhou — fallback pro tray.showMessage")

        if self._tray is None:
            return
        try:
            self._tray.showMessage(
                title, body, QSystemTrayIcon.MessageIcon.Information, 6000
            )
        except Exception:
            log.debug("showMessage falhou", exc_info=True)

    def _show_persistent_toast(
        self, tab_id: int, workspace_id: str, title: str, body: str
    ) -> None:
        """Cria (ou atualiza) o toast in-app pro tab_id e reposiciona a pilha.

        Toca o som de alerta junto. Som NÃO toca em atualização (update) pra
        não bipar de novo a cada re-lembrete — só na primeira aparição.

        Só dispara com a MainWindow visível e não-minimizada: se o app está
        no tray ou minimizado, o usuário não vê esse overlay frameless mesmo,
        e o toast acaba aparecendo centralizado em outro monitor/desktop;
        nesse caso a notificação do S.O. (desktop_notifier) já cobre o aviso.
        """
        if not self.isVisible() or self.isMinimized():
            return
        existing = self._active_toasts.get(tab_id)
        if existing is not None:
            existing.update_content(title, body)
            QTimer.singleShot(0, lambda: position_toasts(list(self._active_toasts.values())))
            return
        sound_name = (
            self.settings.notify_sound_name.strip()
            if self.settings.notify_sound_enabled else ""
        )
        if sound_name:
            # Reusa o player do desktop_notifier — mesma lógica de fallback
            # pw-play/paplay/canberra, role "music" que não fica mutado.
            from ..services.desktop_notifier import _play_sound_async
            _play_sound_async(sound_name)
        toast = PersistentToast(title, body)
        toast.action_clicked.connect(
            lambda _tid=tab_id, _wid=workspace_id:
                self._handle_toast_action(_tid, _wid)
        )
        toast.snoozed.connect(
            lambda _tid=tab_id, _wid=workspace_id:
                self._handle_notification_action(_tid, _wid, "snooze5")
        )
        toast.seen.connect(
            lambda _tid=tab_id, _wid=workspace_id:
                self._handle_notification_action(_tid, _wid, "seen")
        )
        toast.dismissed.connect(
            lambda _tid=tab_id: self._on_toast_dismissed(_tid)
        )
        self._active_toasts[tab_id] = toast
        # Posiciona ANTES e DEPOIS do show. Antes: o WM já recebe a
        # posição no mapping (importa em X11). Depois (via singleShot 0):
        # no Wayland o setGeometry pré-show é frequentemente ignorado e
        # só vale uma chamada depois que o surface foi criado. Sem o
        # segundo reposicionamento, toasts apareciam centralizados na
        # tela em vez do canto top-right.
        position_toasts(list(self._active_toasts.values()))
        toast.show()
        QTimer.singleShot(0, lambda: position_toasts(list(self._active_toasts.values())))

    def _handle_toast_action(self, tab_id: int, workspace_id: str) -> None:
        """Clique em 'Abrir console' no toast — mesma rota da action D-Bus.

        Fecha também a notif D-Bus correspondente, senão fica esquecida no
        canto / na central de notificações depois que o usuário já foi pro
        console.
        """
        self._active_toasts.pop(tab_id, None)
        QTimer.singleShot(0, lambda: position_toasts(list(self._active_toasts.values())))
        nid = self._active_notifications.pop(tab_id, None)
        if nid is not None and self._desktop_notifier is not None:
            self._desktop_notifier.close(nid)
        self._handle_notification_action(tab_id, workspace_id, "open")

    def _on_toast_dismissed(self, tab_id: int) -> None:
        """Usuário clicou no X — toast some, mas não muda estado do inbox."""
        self._active_toasts.pop(tab_id, None)
        QTimer.singleShot(0, lambda: position_toasts(list(self._active_toasts.values())))

    def _close_persistent_toast(self, tab_id: int) -> None:
        """Fecha o toast programaticamente (tab saiu do inbox / mudou estado)."""
        toast = self._active_toasts.pop(tab_id, None)
        if toast is not None:
            toast.hide()
            toast.deleteLater()
            QTimer.singleShot(0, lambda: position_toasts(list(self._active_toasts.values())))

    def _arm_notification_keepalive(self, tab_id: int, is_reminder: bool) -> None:
        """Inicia (ou reinicia) o timer que re-emite a notif a cada 5s.

        Solução pro KDE Plasma 6 transient-izar popups com action: re-emitir
        com `replaces_id` faz o banner reaparecer no canto. Para quando o
        tab sai do inbox ou o usuário clica na action. 5s é menos que o
        timeout que o Plasma aplica (~6s), então o popup não chega a sumir
        entre re-emissões — o banner fica visualmente sticky.
        """
        existing = self._notification_keepalive.get(tab_id)
        if existing is not None:
            existing.stop()
            existing.deleteLater()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(5000)
        timer.timeout.connect(
            lambda _tid=tab_id: self._resurrect_notification(_tid)
        )
        self._notification_keepalive[tab_id] = timer
        timer.start()

    def _cancel_notification_keepalive(self, tab_id: int) -> None:
        timer = self._notification_keepalive.pop(tab_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _resurrect_notification(self, tab_id: int) -> None:
        """Re-emite a notif do tab se ele ainda estiver no inbox.

        Se o tab saiu do inbox no meio (ficou idle, foi clicado, terminou),
        a entry sumiu de `inbox_entries()` e simplesmente paramos. Senão,
        re-chamamos `_on_inbox_alert` como re-lembrete — ele já usa
        `replaces_id` automaticamente via `_active_notifications`.
        """
        self._notification_keepalive.pop(tab_id, None)
        info = self.terminals_coord.inbox_entries().get(tab_id)
        if info is None:
            return
        self._on_inbox_alert(tab_id, info, is_reminder=True)

    def _handle_notification_action(
        self, tab_id: int, workspace_id: str, key: str
    ) -> None:
        """Disparado pelo botão clicado na notificação D-Bus."""
        # O servidor fecha o banner ao invocar action, então o note_id já
        # não é mais válido — descarta pra não tentar close() depois.
        self._active_notifications.pop(tab_id, None)
        self._cancel_notification_keepalive(tab_id)
        if key in ("open", "default"):
            self.show()
            self.raise_()
            self.activateWindow()
            self._focus_tab_from_inbox(workspace_id, tab_id)
        elif key == "snooze5":
            self.terminals_coord.snooze_inbox(tab_id, 5 * 60)
        elif key == "seen":
            self.terminals_coord.dismiss_inbox(tab_id)
        else:
            log.debug("Ação de notificação desconhecida: %s", key)

    def _on_global_dbus_action(self, note_id: int, key: str) -> None:
        """Recebe ActionInvoked de qualquer notificação no bus.

        O notify-hook.py (Stop hook do Claude Code) emite ações com chave
        `open-console:<session_id>`. Como o hook é subprocess separado, o
        DesktopNotifier do app não registra o note_id em `_pending` —
        usamos o sinal global pra interceptar. As actions do inbox alert
        (chaves "open"/"snooze5"/"seen") já são tratadas pelo on_action
        por-nota, então ignoramos elas aqui.
        """
        if not isinstance(key, str) or not key.startswith("open-console:"):
            return
        session_id = key.split(":", 1)[1].strip()
        if not session_id:
            self.show()
            self.raise_()
            self.activateWindow()
            return
        if not self._focus_terminal_by_session_id(session_id):
            self.show()
            self.raise_()
            self.activateWindow()

    def _focus_terminal_by_session_id(self, session_id: str) -> bool:
        """Procura o TerminalWidget com `claimed_session_id == session_id`
        e foca o workspace + aba correspondentes. Retorna True se achou."""
        for workspace_id, area in self.terminals_coord._areas.items():
            for i in range(area.tabs.count()):
                w = area.tabs.widget(i)
                if not isinstance(w, TerminalWidget):
                    continue
                if w.claimed_session_id() == session_id:
                    ws_item = self._find_workspace_item(workspace_id)
                    if ws_item is not None:
                        self.list_widget.setCurrentItem(ws_item)
                    area.tabs.setCurrentIndex(i)
                    self.terminal_host.setCurrentWidget(area)
                    self.show()
                    self.raise_()
                    self.activateWindow()
                    return True
        return False

    def _on_inbox_entry_removed(self, tab_id: int) -> None:
        """Tab saiu do inbox (voltou a trabalhar, terminou, foi focado).
        Fecha a notificação D-Bus correspondente se ainda estiver visível —
        senão o banner "✅ Pronto" continua na tela enquanto o console
        já está em outro estado."""
        self._cancel_notification_keepalive(tab_id)
        self._close_persistent_toast(tab_id)
        # Limpa o debounce — tab saiu do inbox, próxima transição
        # working→idle é genuína e deve disparar notif sem suprimir.
        self._ready_alert_last.pop(tab_id, None)
        nid = self._active_notifications.pop(tab_id, None)
        if nid is None or self._desktop_notifier is None:
            return
        self._desktop_notifier.close(nid)

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
        # Marca o console específico no sidebar (não só o workspace) —
        # ao clicar "Abrir console" na notif, o usuário espera ver o
        # row do console destacado, não só o workspace selecionado.
        target_item = ws_item
        if ws_item is not None:
            if not ws_item.isExpanded():
                ws_item.setExpanded(True)
            for j in range(ws_item.childCount()):
                child = ws_item.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == tab_id:
                    target_item = child
                    break
            self.list_widget.setCurrentItem(target_item)
            self.list_widget.scrollToItem(target_item)
        area = self.terminals_coord.area_for(workspace_id)
        if area is None:
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                # Se o usuário tava na aba "Runners workspace"/"Runners
                # (console)", volta pro "Terminal" — senão a notif só
                # troca a sub-aba invisível.
                self._bottom_tabs.setCurrentWidget(self.terminal_host)
                # Se o terminal pane estiver minimizado, restaura — sem
                # isso o usuário clica na notif e não vê o console.
                if self._terminal_is_minimized():
                    self._toggle_terminal()
                break
        # Traz a janela pra frente — clique na notif do KDE não foca
        # a app sozinho (action invocada via D-Bus não dá activation).
        self.raise_()
        self.activateWindow()

    def _resolve_state(
        self, is_working: bool, is_running: bool, needs_decision: bool = False
    ) -> str:
        if not is_running:
            return STATE_DONE
        if is_working:
            return STATE_WORKING
        if needs_decision:
            return STATE_AWAITING
        return STATE_IDLE

    def _terminal_widget_for(self, tab_id: int) -> TerminalWidget | None:
        for area in self.terminals_coord._areas.values():
            for i in range(area.tabs.count()):
                w = area.tabs.widget(i)
                if id(w) == tab_id and isinstance(w, TerminalWidget):
                    return w
        return None

    def _rename_terminal_session(self, tab_id: int) -> None:
        """Pede um nome custom pra essa sessão e persiste via TerminalWidget.
        Aparece na sidebar e nas notificações (toast / native) imediatamente.
        Deixar vazio remove o nome custom e volta pro preview do prompt."""
        term = self._terminal_widget_for(tab_id)
        if term is None:
            return
        current = term.custom_name()
        name, ok = QInputDialog.getText(
            self,
            "Renomear sessão",
            "Nome custom (vazio pra voltar ao preview do prompt):",
            text=current,
        )
        if not ok:
            return
        term.set_custom_name(name)

    def _close_terminal_by_tab_id(self, tab_id: int) -> None:
        """Encerra e remove a aba de terminal correspondente ao tab_id. Usado
        pelo item 'Encerrar/remover console' do menu de contexto da sidebar."""
        for area in self.terminals_coord._areas.values():
            for i in range(area.tabs.count()):
                w = area.tabs.widget(i)
                if id(w) == tab_id:
                    area._close_tab(i)
                    return

    # Altura fixa do row do QTreeWidget pro TerminalChildWidget. Inclui
    # o overhead de padding 4px (top+bottom = 8px) do ::item — o widget
    # interno mede 52px (sincronizado lá), então row = 52 + 8 = 60.
    _CHILD_HEIGHT = 60

    def _wire_child_actions(
        self, widget: "TerminalChildWidget", tab_id: int
    ) -> None:
        """Conecta ▶ Continuar e ⚙ Modo do row da sidebar ao TerminalWidget
        correspondente. O popup de modo é o mesmo já usado no console
        central, ancorado abaixo-direita do botão clicado."""
        def on_continue() -> None:
            term = self._terminal_widget_for(tab_id)
            if term is not None and term.is_running():
                term.send_continue()

        def on_open_mode_popup(anchor_btn) -> None:
            term = self._terminal_widget_for(tab_id)
            if term is None or not term.is_running():
                return
            from .mode_popup import ModePopup
            popup = ModePopup(
                on_cycle=term.send_cycle_mode,
                on_effort=term.send_open_effort,
                on_model=term.send_open_model,
                parent=anchor_btn,
            )
            global_pos = anchor_btn.mapToGlobal(
                anchor_btn.rect().bottomRight()
            )
            global_pos.setX(global_pos.x() - popup.sizeHint().width())
            global_pos.setY(global_pos.y() + 4)
            popup.show_at(global_pos)

        def on_close() -> None:
            from PySide6.QtWidgets import QMessageBox
            term = self._terminal_widget_for(tab_id)
            title = self._tab_base_titles.get(tab_id, "console")
            running = term is not None and term.is_running()
            msg = (
                f"Encerrar e remover '{title}'?\n\n"
                "O processo Claude será finalizado e a aba removida."
            ) if running else (
                f"Remover '{title}' da sidebar?"
            )
            box = QMessageBox(self)
            box.setWindowTitle("Remover console")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(msg)
            yes_btn = box.addButton("Sim", QMessageBox.ButtonRole.YesRole)
            no_btn = box.addButton("Não", QMessageBox.ButtonRole.NoRole)
            yes_btn.setIcon(QIcon())
            no_btn.setIcon(QIcon())
            box.setDefaultButton(no_btn)
            box.exec()
            if box.clickedButton() is yes_btn:
                self._close_terminal_by_tab_id(tab_id)

        def on_rename() -> None:
            self._rename_terminal_session(tab_id)

        widget.set_action_callbacks(
            on_continue, on_open_mode_popup, on_close, on_rename
        )

    def _add_terminal_child(
        self,
        ws_item: QTreeWidgetItem,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
        needs_decision: bool = False,
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
        state = self._resolve_state(is_working, is_running, needs_decision)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        # Layout do workspace na sidebar: "Runners workspace" no topo,
        # depois a lista de consoles. O group de runners (quando existe)
        # é inserido em index 0; consoles vão sempre ao final.
        ws_item.addChild(child)
        self.list_widget.setItemWidget(child, 0, widget)
        # Conecta os botões inline (▶ ⚙) à TerminalWidget correspondente.
        # Visibilidade respeita o toggle do header WORKSPACES.
        self._wire_child_actions(widget, tab_id)
        widget.set_actions_visible(self.settings.show_terminal_actions)
        widget.set_actions_enabled(is_running)
        # ▶ só faz sentido em sessões restauradas via --resume após o app
        # reabrir; em sessão fresca ele fica oculto.
        widget.set_continue_eligible(
            term is not None and term.was_restored_on_startup()
        )
        # Tarefas concluídas (processo finalizado) ficam ocultas na sidebar.
        child.setHidden(state == STATE_DONE)
        ws_item.setExpanded(True)
        self.terminals_coord.state.tree_items[tab_id] = child
        # Reaplica sufixos de desambiguação no workspace inteiro (cobre o
        # caso de a nova aba colidir com outra que já estava sem sufixo).
        self._refresh_workspace_child_titles(ws_item)
        # Já dispara um request de git status pra esse cwd — assim o
        # label aparece logo na primeira pintura, sem esperar o tick.
        cwd = term.claude_cwd() if term is not None else None
        if cwd:
            self._repo_poller.request(cwd)
        # Anexa os runners deste console como filhos do tree item.
        ws_data = ws_item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(ws_data, Workspace):
            self._install_console_runner_children(child, ws_data, tab_id)
        self._refresh_empty_placeholder(ws_item)

    def _update_terminal_child(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
        needs_decision: bool = False,
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
        state = self._resolve_state(is_working, is_running, needs_decision)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        widget.set_actions_enabled(is_running)
        # Reflete a flag de "restaurado no startup" — durante a vida do
        # tab ela só vira True (uma vez), mas updates posteriores (state,
        # título) chegam aqui também e precisam manter o sinal coerente.
        widget.set_continue_eligible(
            term is not None and term.was_restored_on_startup()
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
        """Prepende `#N ` ao título, onde N é a posição do console entre
        os irmãos do mesmo workspace (ordenado por tab_id crescente — o
        mais antigo é #1). Assim cada workspace numera seus consoles de
        forma independente e sempre sequencial."""
        if not base_title or ws_item is None:
            return base_title
        sibling_ids: list[int] = []
        for i in range(ws_item.childCount()):
            sib = ws_item.child(i)
            sib_id = sib.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(sib_id, int):
                sibling_ids.append(sib_id)
        if int(tab_id) not in sibling_ids:
            sibling_ids.append(int(tab_id))
        sibling_ids.sort()
        position = sibling_ids.index(int(tab_id)) + 1
        return f"#{position} {base_title}"

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
            if not isinstance(sib_id, int):
                continue
            sib_widget = self.list_widget.itemWidget(sib, 0)
            if not isinstance(sib_widget, TerminalChildWidget):
                continue
            base = self._tab_base_titles.get(sib_id, "")
            if not base:
                continue
            full = base
            term = self._terminal_widget_for(sib_id)
            if term is not None:
                full = term.full_title() or base
            display = self._compute_disambiguated_title(ws_item, sib_id, base)
            sib_widget.set_title(display, full)

    # ---------- git info na sidebar ----------

    def _refresh_terminal_git_info(self) -> None:
        """Itera os children visíveis e pede status do repo + atualiza
        modelo/tokens da sessão. Status do git cai em `_on_repo_status_ready`
        quando prontos; modelo/tokens é setado direto (leitura síncrona
        rápida do JSONL claimed)."""
        from ..usage_telemetry import context_window_for_model, usage_for_session

        for tab_id, item in list(self.terminals_coord.state.tree_items.items()):
            if item is None or item.isHidden():
                continue
            widget = self.list_widget.itemWidget(item, 0)
            if not isinstance(widget, TerminalChildWidget):
                continue
            term = self._terminal_widget_for(tab_id)
            if term is None:
                continue
            cwd = term.claude_cwd()
            if cwd:
                self._repo_poller.request(cwd)
            # Modelo + tokens da sessão claimed. usage_for_session é leve
            # (lê apenas a usage de cada linha do JSONL).
            session_path = term.claimed_session_path()
            if session_path is None:
                widget.update_session_info("", 0, 0, 0)
                continue
            try:
                stats = usage_for_session(session_path)
            except Exception:
                log.debug("falha ao agregar usage %s", session_path, exc_info=True)
                continue
            cache = stats.cache_creation_tokens + stats.cache_read_tokens
            ctx_window = context_window_for_model(stats.last_model or "")
            widget.update_session_info(
                stats.last_model or "",
                stats.input_tokens,
                stats.output_tokens,
                cache,
                context_tokens=stats.last_context_tokens,
                context_window=ctx_window,
            )
        # Status do uso do plano (janela de 5h) — label acima do "Novo
        # Workspace". Replica o `Plan usage limits → Current session` do
        # claude.ai.
        self._refresh_plan_usage_status()

    def _on_context_status_refresh_clicked(self) -> None:
        """Click no botão ⟳ ao lado do status do plano: força chamada
        nova ignorando o cache TTL. Em cooldown (rate-limit), o force
        é ignorado dentro do fetch (forçar só renova o 429), e a UI
        apenas re-renderiza com o estado atual. Feedback visual:
        desabilita o botão durante a request pra evitar double-click."""
        btn = getattr(self, "_context_status_refresh_btn", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("…")
        try:
            self._refresh_plan_usage_status(force=True)
        finally:
            if btn is not None:
                btn.setText("⟳")
                btn.setEnabled(True)

    def _refresh_plan_usage_status(self, force: bool = False) -> None:
        """Atualiza o label de uso do plano na sidebar numa única linha
        compacta tipo `5h 34% · sem 41% · son 12%` (cores no número,
        rótulos em cinza claro). Detalhes completos (reset, fonte,
        timestamp de sync) ficam no tooltip pra não consumir altura.

        Em cooldown da API, mostra `Uso: cooldown 44m ⟳` numa linha só
        em vez do banner de 2 linhas anterior.

        Estratégia: tenta `/api/oauth/usage` (mesmo endpoint que o
        `/status` do Claude Code consome — números idênticos ao
        claude.ai). Se token ausente, expirado ou request falha, cai
        pro cálculo USD-baseado a partir dos JSONLs locais."""
        from datetime import datetime, timedelta, timezone

        from ..plan_usage_api import cooldown_remaining_seconds, fetch_plan_usage
        from ..usage_telemetry import recent_plan_usage, weekly_plan_usage

        label = getattr(self, "_context_status_label", None)
        container = getattr(self, "_context_status_container", None)
        if label is None:
            return

        def _set_container_visible(visible: bool) -> None:
            if container is not None:
                container.setVisible(visible)
            else:
                label.setVisible(visible)

        def _color(p: float) -> str:
            if p < 50:
                return theme.SUCCESS
            if p < 80:
                return theme.WARNING
            return theme.DANGER

        # --- 1. Caminho preferido: API oficial ---
        snap = None
        try:
            snap = fetch_plan_usage(force=force)
        except Exception:  # noqa: BLE001
            log.debug("fetch_plan_usage falhou", exc_info=True)

        if snap is not None and (
            snap.five_hour is not None
            or snap.seven_day is not None
            or snap.seven_day_sonnet is not None
        ):
            chips: list[str] = []
            tooltip_lines: list[str] = ["Plan usage limits (via /api/oauth/usage)"]

            def _reset_phrase(reset_at):
                if reset_at is None:
                    return ""
                delta = reset_at - datetime.now(timezone.utc)
                mins_left = max(int(delta.total_seconds() // 60), 0)
                if mins_left >= 60:
                    return f"{mins_left // 60}h{mins_left % 60:02d}m"
                return f"{mins_left}m"

            def _chip(label_txt: str, pct: float) -> str:
                return (
                    f"<span style='color: {theme.TEXT_FAINT};'>{label_txt} </span>"
                    f"<span style='color: {_color(pct)}; font-weight: 600;'>"
                    f"{pct:.0f}%</span>"
                )

            if snap.five_hour is not None:
                pct = snap.five_hour.utilization_pct
                reset_str = _reset_phrase(snap.five_hour.resets_at)
                chips.append(_chip("5h", pct))
                tip = f"Sessão 5h: {pct:.0f}%"
                if snap.five_hour.resets_at is not None:
                    tip += (
                        "  ·  reseta "
                        f"{snap.five_hour.resets_at.astimezone().strftime('%H:%M')}"
                        f" ({reset_str})"
                    )
                tooltip_lines.append(tip)

            if snap.seven_day is not None:
                pct = snap.seven_day.utilization_pct
                chips.append(_chip("sem", pct))
                reset_at = snap.seven_day.resets_at
                tip = f"Semana (todos): {pct:.0f}%"
                if reset_at is not None:
                    tip += (
                        "  ·  reseta "
                        f"{reset_at.astimezone().strftime('%a %d/%m %H:%M')}"
                    )
                tooltip_lines.append(tip)

            if snap.seven_day_sonnet is not None:
                pct = snap.seven_day_sonnet.utilization_pct
                chips.append(_chip("son", pct))
                tooltip_lines.append(f"Semana (Sonnet): {pct:.0f}%")

            if snap.seven_day_opus is not None:
                tooltip_lines.append(
                    f"Semana (Opus): {snap.seven_day_opus.utilization_pct:.0f}%"
                )

            if chips:
                self._last_plan_usage_sync_at = datetime.now()
                sync_str = self._last_plan_usage_sync_at.strftime("%H:%M:%S")
                sep = (
                    f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
                )
                label.setText(sep.join(chips))
                tooltip_lines.append(f"sync {sync_str} · fonte: API")
                label.setToolTip("\n".join(tooltip_lines))
                _set_container_visible(True)
                return

        # API falhou. Se estamos em cooldown explícito (rate limit), o
        # fallback USD-baseado dá valores muito errados (caso real:
        # claude.ai 34%, fallback 100%) — melhor mostrar só o aviso de
        # cooldown e deixar o usuário aguardar/clicar no refresh
        # depois do retry-after, em vez de mentir com % estimado.
        cooldown_now = cooldown_remaining_seconds()
        if cooldown_now > 0:
            mins = max(1, cooldown_now // 60)
            label.setText(
                f"<span style='color: {theme.TEXT_FAINT};'>Uso: </span>"
                f"<span style='color: {theme.WARNING};'>cooldown {mins}m</span>"
            )
            label.setToolTip(
                "/api/oauth/usage está rate-limited.\n"
                f"Próxima tentativa permitida em {mins} minutos "
                "(servidor manda Retry-After).\n"
                "Clique ⟳ depois disso pra sincronizar.\n"
                "Os números do fallback USD-baseado são imprecisos pra "
                "Max 5x (não há mapeamento público token→cota), por isso "
                "estão ocultos até a API responder."
            )
            _set_container_visible(True)
            return

        # --- 2. Fallback: cálculo USD-baseado a partir dos JSONLs ---
        try:
            usage = recent_plan_usage(5 * 3600)
            weekly = weekly_plan_usage(7)
        except Exception:  # noqa: BLE001
            log.debug("falha ao agregar uso do plano", exc_info=True)
            _set_container_visible(False)
            return
        if (usage.first_ts is None or usage.cost_usd <= 0) and weekly.all_cost_usd <= 0:
            _set_container_visible(False)
            return

        chips: list[str] = []
        reset_5h_str = ""
        reset_5h_wall = ""
        sess_pct = 0.0

        def _chip(label_txt: str, pct: float) -> str:
            return (
                f"<span style='color: {theme.TEXT_FAINT};'>{label_txt} </span>"
                f"<span style='color: {_color(pct)}; font-weight: 600;'>"
                f"{pct:.0f}%</span>"
            )

        if usage.first_ts is not None and usage.cost_usd > 0:
            limit_5h = max(self.settings.plan_usd_limit_5h, 0.01)
            sess_pct = min(usage.cost_usd / limit_5h * 100.0, 999.0)
            reset_at = usage.first_ts + timedelta(hours=5)
            delta = reset_at - datetime.now(timezone.utc)
            mins_left = max(int(delta.total_seconds() // 60), 0)
            reset_5h_str = (
                f"{mins_left // 60}h{mins_left % 60:02d}m"
                if mins_left >= 60
                else f"{mins_left}m"
            )
            reset_5h_wall = reset_at.astimezone().strftime("%H:%M")
            chips.append(_chip("5h", sess_pct))

        # Reset semanal: próxima segunda 07:00 local (só pro tooltip agora).
        now_local = datetime.now().astimezone()
        days_until_monday = (7 - now_local.weekday()) % 7
        next_monday = (now_local + timedelta(days=days_until_monday)).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
        if next_monday <= now_local:
            next_monday += timedelta(days=7)

        limit_all = max(self.settings.plan_weekly_usd_limit_all, 0.01)
        all_pct = min(weekly.all_cost_usd / limit_all * 100.0, 999.0)
        chips.append(_chip("sem", all_pct))

        limit_sonnet = max(self.settings.plan_weekly_usd_limit_sonnet, 0.01)
        sonnet_pct = min(weekly.sonnet_cost_usd / limit_sonnet * 100.0, 999.0)
        chips.append(_chip("son", sonnet_pct))

        cooldown = cooldown_remaining_seconds()
        cooldown_note = ""
        if cooldown > 0:
            mins = cooldown // 60
            cooldown_note = (
                f"\nAPI /api/oauth/usage em cooldown ({mins}min restantes — "
                f"rate-limited). Reabra após esse tempo pra ver os % reais."
            )
        sep = f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
        label.setText(sep.join(chips))
        label.setToolTip(
            "Plan usage limits (fallback USD-baseado — API indisponível)"
            + cooldown_note + "\n"
            f"Sessão 5h: ${usage.cost_usd:.2f} / ${self.settings.plan_usd_limit_5h:.0f}"
            f"  →  {sess_pct:.0f}%"
            + (
                f"\n  Sessão começou: "
                f"{usage.first_ts.astimezone().strftime('%H:%M')}"
                f"  ·  Reseta às {reset_5h_wall} ({reset_5h_str})"
                if usage.first_ts
                else ""
            )
            + f"\nSemana (todos): ${weekly.all_cost_usd:.2f} / "
            f"${self.settings.plan_weekly_usd_limit_all:.0f}  →  {all_pct:.0f}%"
            f"\nSemana (Sonnet): ${weekly.sonnet_cost_usd:.2f} / "
            f"${self.settings.plan_weekly_usd_limit_sonnet:.0f}  →  {sonnet_pct:.0f}%"
            f"\nReset semanal: {next_monday.strftime('%a %d/%m %H:%M')}\n"
            "Ajuste os limites `plan_usd_limit_5h`, "
            "`plan_weekly_usd_limit_all` e `plan_weekly_usd_limit_sonnet` "
            "em settings.json pra calibrar com claude.ai."
        )
        _set_container_visible(True)

    def _on_repo_status_ready(
        self, folder: str, branch: str, modified: int
    ) -> None:
        """Aplica branch+contagem em todos os children cuja claude_cwd
        bate com `folder`. Um mesmo folder pode aparecer em vários
        consoles do mesmo (ou de outro) workspace."""
        for tab_id, item in list(self.terminals_coord.state.tree_items.items()):
            if item is None:
                continue
            widget = self.list_widget.itemWidget(item, 0)
            if not isinstance(widget, TerminalChildWidget):
                continue
            term = self._terminal_widget_for(tab_id)
            if term is None or term.claude_cwd() != folder:
                continue
            widget.update_git_info(branch, modified)

    def _launch_claude_for(
        self,
        workspace: Workspace,
        resume_session_id: str,
        cwd_override: str,
        restored_on_startup: bool = False,
    ) -> None:
        terminal = self.launch_coord.launch_claude(
            workspace, resume_session_id, cwd_override
        )
        if terminal is not None:
            if restored_on_startup:
                # Habilita o ▶ continuar nessa aba — só sessões reabertas
                # via _restore_sessions têm tarefa potencialmente
                # interrompida. Sessões criadas "no app vivo" (botão Novo
                # Workspace, Retomar de session card, etc) não setam.
                terminal.mark_restored_on_startup()
            self._wire_terminal_runner_panel(workspace, terminal)
            # Se o console restaurado tem runners persistidos (matching
            # console_session_id), garante a RunnerArea já criada — assim
            # o painel "Runners (console)" não aparece vazio até o user
            # clicar em ▤ Runners, e o grupo "Runners console" da sidebar
            # consegue ler o sid da area pra ligar os children.
            sid = terminal.claimed_session_id() or ""
            if sid and any(
                (r.console_session_id or "") == sid for r in workspace.runners
            ):
                self._ensure_terminal_runner_panel(workspace, terminal)
            area = self.terminals_coord.area_for(workspace.id)
            if area is not None:
                self.terminal_host.setCurrentWidget(area)
                self._bottom_tabs.setCurrentWidget(self.terminal_host)

    def _handoff_session(self, workspace: Workspace, session) -> None:
        self.launch_coord.handoff_session(workspace, session)

    def _launch_shell_for(self, workspace: Workspace) -> None:
        terminal = self.launch_coord.launch_shell(workspace)
        if terminal is not None:
            area = self.terminals_coord.area_for(workspace.id)
            if area is not None:
                self.terminal_host.setCurrentWidget(area)
                self._bottom_tabs.setCurrentWidget(self.terminal_host)

    def _cleanup_terminal_for(self, workspace_id: str) -> None:
        self.plugin_coord.dispatch_workspace_closed(workspace_id)
        area = self.terminals_coord.cleanup_area(workspace_id)
        if area is not None:
            self.terminal_host.removeWidget(area)
            area.deleteLater()
            if self.terminal_host.count() == 1:
                self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)
        runner_area = self._runner_areas.pop(workspace_id, None)
        if runner_area is not None:
            runner_area.close_all()
            self.runner_host.removeWidget(runner_area)
            runner_area.deleteLater()
            if self.runner_host.count() == 1:
                self.runner_host.setCurrentIndex(self._runner_placeholder_idx)
        # RunnerAreas dos consoles desse workspace moram no top tab
        # "Runners (console)" — remove cada uma do QStackedWidget antes
        # de soltar o registry.
        for stale in (self._console_runner_areas.pop(workspace_id, {}) or {}).values():
            self.console_runner_host.removeWidget(stale)
            stale.deleteLater()
        self._sync_console_runner_host()

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

    def _ensure_no_ctx_area(self) -> TerminalArea:
        """Cria sob demanda uma TerminalArea sem workspace pra hospedar
        abas 'sem contexto'. Vive no terminal_host (QStackedWidget) junto
        com as areas dos workspaces — a cada clique nos atalhos da sidebar
        adicionamos uma aba nova nessa area."""
        area = getattr(self, "_no_ctx_area", None)
        if area is None:
            area = TerminalArea()
            self._no_ctx_area = area
            self.terminal_host.addWidget(area)
        return area

    def _launch_terminal_no_ctx(self) -> None:
        """Abre um shell embutido em $HOME como nova aba na area 'sem ctx'."""
        area = self._ensure_no_ctx_area()
        home = str(Path.home())
        title = f"shell (sem ctx) #{area.count() + 1}"
        terminal = area.add_terminal(title)
        try:
            terminal.start_interactive_shell(
                home, shell=self.settings.shell_command or None
            )
        except Exception as e:
            log.exception("Falha ao abrir terminal sem contexto embutido")
            QMessageBox.warning(self, "Falha ao abrir terminal", str(e))
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

    def _launch_claude_no_ctx(self) -> None:
        """Abre o Claude embutido em $HOME como nova aba na area 'sem ctx'."""
        area = self._ensure_no_ctx_area()
        home = str(Path.home())
        title = f"claude (sem ctx) #{area.count() + 1}"
        terminal = area.add_terminal(title)
        terminal.configure_claude(home)
        argv = [self.settings.claude_command, *self.settings.claude_extra_args]
        try:
            terminal.start_shell_command(
                argv,
                home,
                label="claude (sem ctx)",
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir Claude sem contexto embutido")
            QMessageBox.warning(self, "Falha ao abrir Claude", str(e))
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

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
                self._launch_claude_for(
                    ws, entry.session_id, entry.cwd, restored_on_startup=True
                )
                restored += 1
            except Exception:
                log.exception("Falha ao restaurar sessão %s", entry.session_id)
        if restored:
            log.info("Restauradas %d sessão(ões) Claude da execução anterior", restored)

    def _open_plugin_palette(self) -> None:
        """Ctrl+P: dialog com comandos declarados por plugins habilitados."""
        self.plugin_coord.open_palette(self)
