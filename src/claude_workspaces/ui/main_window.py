import logging
from datetime import UTC
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QCursor,
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
    QPushButton,
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

from ..claude_sessions import list_sessions_for_paths_backend
from ..errors import LaunchError
from ..hook_manager import refresh_installed_hook
from ..launchers import (
    LauncherError,
    find_app_repo_root,
    launch_claude_in_dir,
)
from ..logging_utils import log_exceptions
from ..models import Workspace
from ..notifications import (
    NotificationKind,
    NotificationPriority,
    NotificationService,
)
from ..notifications.center import NotificationCenter
from ..repo_status_poller import RepoStatusPoller
from ..services.desktop_notifier import DesktopNotifier
from ..services.quick_open import find_files
from ..services.system_open import open_in_file_manager
from ..session_persistence import (
    SavedSession,
    load_saved_sessions,
    save_sessions,
)
from ..settings import Settings
from . import theme
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
from .persistent_toast import PersistentToast, position_toasts
from .runner_area import RunnerArea
from .runner_edit_dialog import RunnerEditDialog
from .session_export_dialog import open_session_export_dialog
from .settings_panel import SettingsPanel
from .shortcuts_dialog import ShortcutsDialog
from .skills_panel import SkillsPanel
from .terminal_area import TerminalArea
from .terminal_child_widget import (
    STATE_AWAITING,
    STATE_DONE,
    STATE_IDLE,
    STATE_PLANNING,
    STATE_WORKING,
    TerminalChildWidget,
)
from .terminal_widget import TerminalWidget
from .theme import (
    LAYOUT_SAVE_DEBOUNCE_MS,
    RIGHT_DOCK_DEFAULT_W,
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
        self._runner_tree_items: dict[str, dict[str, QTreeWidgetItem]] = {}
        # workspace_id → QTreeWidgetItem (header "Runners workspace")
        self._runner_group_items: dict[str, QTreeWidgetItem] = {}
        # (workspace_id, tab_id) → QTreeWidgetItem (header "Runners console")
        self._console_runner_group_items: dict[
            tuple[str, int], QTreeWidgetItem
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
        self.terminals_coord.tab_session_exited.connect(self._on_tab_session_exited)
        # Sino agora reflete o unread real do NotificationService (criado abaixo).
        self.terminals_coord.spinner_tick.connect(self._on_spinner_tick)
        self.terminals_coord.terminal_area_created.connect(self._on_area_created)
        self.terminals_coord.inbox_alert.connect(self._on_inbox_alert)
        self.terminals_coord.inbox_entry_removed.connect(
            self._on_inbox_entry_removed
        )

        # ---------- Notification service (novo) ----------
        # Único ponto de verdade pra sino + center + (em commits subsequentes)
        # tray e badges. terminals_coord continua emitindo inbox_alert (working
        # → idle), e `_on_inbox_alert` espelha pro service.notify(...).
        from ..storage import config_dir as _cfg_dir
        self.notif_service = NotificationService(
            _cfg_dir() / "notifications.json", parent=self
        )
        self.notif_service.unread_count_changed.connect(self.top_bar.set_inbox_count)
        self.notif_service.unread_count_changed.connect(
            lambda _c: self._refresh_unread_badges()
        )
        self.notif_service.reminder_due.connect(self._on_notif_reminder_due)
        # Inicializa a contagem do sino imediatamente — service pode ter
        # itens vindos do disco antes do primeiro signal.
        self.top_bar.set_inbox_count(self.notif_service.unread_count())
        # Settings panel já foi criado no _build_ui — agora que o service
        # existe, injeta pra ativar a sub-seção "Centro de Notificações".
        self.settings_panel.set_notification_service(self.notif_service)

        # Webhook do Discord — espelha notification_added num canal. Lê as
        # settings via providers, então toggle/URL passam a valer sem recriar
        # o adapter (basta salvar nas Configurações).
        try:
            from ..notifications.discord import DiscordWebhookAdapter
            self._discord_adapter = DiscordWebhookAdapter(
                self.notif_service,
                enabled_provider=lambda: self.settings.discord_webhook_enabled,
                url_provider=lambda: self.settings.discord_webhook_url,
                workspace_name_provider=self._workspace_name_for_notif,
                parent=self,
            )
        except Exception:
            log.exception("falha ao montar DiscordWebhookAdapter")

        # Long-running detection: tab_id → epoch em que entrou em "working".
        # Limpo quando volta pra idle/done. Timer abaixo escaneia a cada
        # 30s e emite `long_running` ao passar do threshold (5 min).
        self._working_since: dict[int, float] = {}
        self._long_running_notified: set[int] = set()
        self._long_running_timer = QTimer(self)
        self._long_running_timer.setInterval(30_000)
        self._long_running_timer.timeout.connect(self._scan_long_running)
        self._long_running_timer.start()
        # Center (popup) — criado preguiçosamente na primeira abertura.
        self._notif_center: NotificationCenter | None = None
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

        # Tick de 30s só pra atualizar o "atualizado há Xmin atrás"
        # debaixo do Usage — re-renderiza o texto relativo a partir do
        # _last_plan_usage_sync_at já armazenado, não refaz fetch.
        self._plan_usage_updated_timer = QTimer(self)
        self._plan_usage_updated_timer.setInterval(30_000)
        self._plan_usage_updated_timer.timeout.connect(
            self._refresh_plan_usage_updated_label
        )
        self._plan_usage_updated_timer.start()

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
        self.top_bar.toggle_right_dock_clicked.connect(self._toggle_right_dock)
        self.top_bar.inbox_clicked.connect(self._show_inbox)
        outer.addWidget(self.top_bar)

        splitter_css = (
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3a3a3a; }"
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
        # Impede que larguras mínimas dos filhos (TerminalArea, RunnerArea…)
        # se propaguem pra cima do splitter e forcem scroll horizontal.
        self.right_splitter.setMinimumWidth(0)

        self.content_stack = QStackedWidget()
        self.details = WorkspaceDetailsPanel(self.settings)
        self.details.edit_requested.connect(self.edit_workspace)
        self.details.delete_requested.connect(self.delete_workspace)
        self.details.pin_toggle_requested.connect(self._toggle_pin_workspace)
        self.details.minimize_toggle_requested.connect(self._toggle_content_minimized)
        self.details.launch_claude_requested.connect(
            lambda ws, sid, cwd, backend: self._launch_claude_for(
                ws, sid, cwd, backend=backend
            )
        )
        self.details.launch_shell_requested.connect(self._launch_shell_for)
        self.details.open_file_requested.connect(self._open_file_in_editor)
        self.details.handoff_requested.connect(self._handoff_session)
        self.details.export_session_requested.connect(self._export_session)
        self.content_stack.addWidget(self.details)

        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.set_workspace_getter(self._current_workspace)
        self.settings_panel.settings_saved.connect(self._on_settings_saved)
        self.settings_panel.minimize_requested.connect(self._toggle_content_minimized)
        if hasattr(self, "notif_service"):
            self.settings_panel.set_notification_service(self.notif_service)
        # Wrap em QScrollArea — SettingsPanel tem várias rows de form
        # e seu minimumSizeHint natural (~870px) trava o right_splitter
        # com collapsible=False, impedindo o terminal de crescer/maximizar.
        self._settings_scroll = QScrollArea()
        self._settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setWidget(self.settings_panel)
        # setMinimumWidth(0) impede que o QScrollArea propague o mínimo
        # do SettingsPanel (~870px) pro QStackedWidget acima — sem isso,
        # content_stack sempre exige ≥870px de largura e força scroll
        # horizontal na janela mesmo quando Settings não está visível.
        self._settings_scroll.setMinimumWidth(0)
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
        self._terminal_pane.setMinimumWidth(0)
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

        # Dock direito (3ª coluna): Tarefas + Git + Skills colapsáveis.
        # NÃO forçamos minimumWidth aqui — o próprio RightDock controla seu
        # min/max (strip de 36px quando colapsado, ≥256px com painel aberto).
        # Forçar min aqui conflitava com o maxWidth(36) interno e quebrava o
        # layout. A garantia de "sempre visível" é feita no startup abrindo
        # um painel default + botão na activity bar.
        self.right_dock = self._build_right_dock()

        # Container do center: right_splitter (painéis verticais) +
        # MinimizeTray fixa na base. Cada painel minimizado vira chip
        # na tray; click no chip restaura.
        from .minimize_tray import MinimizeTray
        center_host = QWidget()
        # Barreira de topo: nenhum filho do centro propaga largura mínima
        # pra o dock manager — sem isso qualquer widget profundo (runner
        # toolbar, label longo de branch…) pode forçar scroll horizontal.
        center_host.setMinimumWidth(0)
        ch_layout = QVBoxLayout(center_host)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        ch_layout.setSpacing(0)
        ch_layout.addWidget(self.right_splitter, stretch=1)
        self._minimize_tray = MinimizeTray()
        self._minimize_tray.restore_requested.connect(self._on_minimize_tray_restore)
        ch_layout.addWidget(self._minimize_tray)

        # Monta os 3 docks. ORDEM IMPORTA: center primeiro — se left/right
        # entrarem antes, o QtAds não tem dock area pra ancorar e cria um
        # segundo dock area no mesmo lado (sidebar duplicando, etc).
        self._center_dock = self.body_dock.add_center(center_host, "Workspace")
        self._sidebar_dock = self.body_dock.add_left(self._sidebar, "Sidebar")
        self._right_panel_dock = self.body_dock.add_right(self.right_dock, "Ferramentas")

        # NOTA: hide das title bars (sidebar/center) acontece DEPOIS do
        # safety net abaixo — o toggleView recria o dockAreaWidget e
        # apaga o setVisible(False).

        # Restaura layout salvo (tamanhos das colunas). Fallback: ~240/760/340.
        # Schema bumps:
        #  1 = ordem center→left→right corrigida (0.54.1)
        #  2 = título do center escondido + close button desabilitado +
        #      garantia de que sidebar/ferramentas voltam visíveis (0.55.3)
        #  3 = força sidebar/ferramentas visíveis SEMPRE no startup,
        #      mesmo após restoreState — o safety net da 0.55.3 não
        #      funcionava quando o dock saía removido do container (0.55.5)
        _DOCK_SCHEMA = 3
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
        # Safety net AGRESSIVO: força sidebar e ferramentas visíveis SEMPRE
        # ao subir, independente do que veio do state restaurado. Quando
        # o user fecha pela title bar, o dock é removido do container e
        # toggleView() condicional não traz de volta — chamar setVisible
        # + toggleView garante o re-anexar.
        for key in ("sidebar", "ferramentas"):
            d = self.body_dock.dock(key)
            if d is not None:
                d.toggleView(True)
                d.setAsCurrentTab()
        # Fecha todos os containers flutuantes que restoreState possa ter
        # criado — evita janelas "▶ Continuar" aparecendo fora do app.
        n_closed = self.body_dock.close_all_floating()
        if n_closed:
            log.info("[DOCK] %d container(s) flutuante(s) fechados no startup", n_closed)
        # Re-ancora docks que state salvo possa ter deixado floating ou
        # fora do viewport (sidebar some da tela, ferramentas vira janela
        # flutuante separada).
        self.body_dock.redock_left("sidebar")
        self.body_dock.redock_right("ferramentas")
        # Garante que o dock "Ferramentas" da direita SEMPRE apareça com
        # conteúdo: se nenhum painel estiver aberto (todos colapsados no
        # state salvo), abre o primeiro painel default_open. Sem isso o dock
        # virava uma faixa de 36px que o usuário não achava como exibir.
        if not self.right_dock.open_panels():
            default_pid = next(
                (s.panel_id for s in self.DOCK_PANEL_SPECS if s.default_open),
                self.DOCK_PANEL_SPECS[0].panel_id if self.DOCK_PANEL_SPECS else None,
            )
            if default_pid is not None:
                self.right_dock.set_panel_open(default_pid, True)
        ra = self._right_panel_dock.dockAreaWidget()
        if ra is not None and ra.width() < 120:
            ra.resize(RIGHT_DOCK_DEFAULT_W, ra.height() or 600)

        # AGORA esconde as title bars (precisa ser após o toggleView,
        # senão o area recriado restaura a barra visível).
        for d in (self._center_dock, self._sidebar_dock):
            area = d.dockAreaWidget()
            if area is not None:
                area.titleBar().setVisible(False)

        # Botão de minimizar na title bar do dock "Ferramentas" — esconde o
        # painel (mesmo toggle do botão da topbar / Ctrl+Shift+B), simétrico
        # ao fato de a sidebar ter o toggle de bars na topbar esquerda.
        self._install_ferramentas_minimize_btn()

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

        # ---------- Status bar ----------
        from .status_bar import StatusBarWidgets
        self.status_widgets = StatusBarWidgets()
        sb = self.statusBar()
        sb.setStyleSheet("QStatusBar { background: #161616; border-top: 1px solid #2a2a2a; }")
        sb.setSizeGripEnabled(False)
        sb.addPermanentWidget(self.status_widgets, stretch=1)
        # Click no segmento de workspace foca a sidebar/seleciona o
        # workspace ativo; click no console_state foca o console ativo.
        self.status_widgets.workspace.clicked.connect(self._focus_active_workspace_from_status)
        self.status_widgets.console_state.clicked.connect(self._focus_active_console_from_status)

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
        # Restaura panes minimizados salvos. Deferido pra rodar depois
        # do show() — splitter.height() é 0 enquanto a window não foi
        # mostrada, e o setSizes não cola corretamente.
        QTimer.singleShot(0, self._restore_minimized_panes)

    def _restore_minimized_panes(self) -> None:
        """Re-aplica `settings.minimized_panes` no startup — chip na
        tray + visibilidade colapsada do pane correspondente. Aplica
        estado direto (setVisible + chip) sem depender de
        `_content_is_minimized` etc., porque o `right_splitter_sizes`
        salvo já vem com sizes minimizados (ex.: [0, total] pro
        workspace) e os toggles antigos checavam o size pra decidir
        se viraria estado — pulando o efeito visual."""
        try:
            panes = list(self.settings.minimized_panes or [])
        except Exception:
            return
        if not panes:
            return

        if "workspace" in panes:
            sizes = self.right_splitter.sizes()
            total = sum(sizes) or 800
            if sizes and sizes[0] > 50:
                self._content_last_size = sizes[0]
            self.content_stack.setVisible(False)
            self.right_splitter.setSizes([0, total])
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.add_chip(
                    "workspace", "Workspace", "fa5s.folder-open"
                )
            if hasattr(self, "details"):
                self.details.refresh_minimize_btn(True)

        if hasattr(self, "_bottom_sub_splitter"):
            self._terminal_pane_widget.setMinimumHeight(0)
            self._runners_pane.setMinimumHeight(0)
            self._runners_console_pane.setMinimumHeight(0)

            # Usa os toggles direto — fonte única de verdade pro min/max.
            # Ignora panes já minimizados (toggle inverte estado).
            if "terminal_pane" in panes and not self._terminal_pane_is_minimized():
                self._toggle_terminal_pane_minimized()
            if "runners" in panes and not self._runners_pane_is_minimized():
                self._toggle_runners_minimized()
            if "runners_console" in panes and not self._runners_console_pane_is_minimized():
                self._toggle_runners_console_minimized()

    def _schedule_layout_save(self, *_args) -> None:
        self._layout_save_timer.start()

    @log_exceptions(message="Falha ao persistir layout ao vivo")
    def _persist_layout(self) -> None:
        self.settings.body_dock_state = self.body_dock.save_state_b64()
        self.settings.right_splitter_sizes = list(self.right_splitter.sizes())
        if hasattr(self, "_bottom_sub_splitter"):
            self.settings.bottom_sub_splitter_sizes = list(
                self._bottom_sub_splitter.sizes()
            )
        # Persiste quais panes estavam minimizados — read estado direto
        # dos checkers `_content_is_minimized` etc., única fonte de
        # verdade. Restaurado no setup pra reaparecer chip + área
        # colapsada exatamente como o user deixou.
        minimized: list[str] = []
        if self._content_is_minimized():
            minimized.append("workspace")
        if hasattr(self, "_bottom_sub_splitter"):
            if self._terminal_pane_is_minimized():
                minimized.append("terminal_pane")
            if self._runners_pane_is_minimized():
                minimized.append("runners")
            if self._runners_console_pane_is_minimized():
                minimized.append("runners_console")
        self.settings.minimized_panes = minimized
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
        return sizes[1] <= 4  # colapsado (com chip na MinimizeTray)

    def _toggle_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        if not sizes or len(sizes) < 2:
            return
        if not self._terminal_is_minimized():
            # Minimizar: colapsa o pane inteiro pra 0 + chip na tray
            self._terminal_last_size = sizes[1] if sizes[1] > 50 else 420
            self.terminal_host.setVisible(False)
            self.right_splitter.setSizes([sum(sizes), 0])
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.add_chip(
                    "terminal", "Terminal", "fa5s.terminal"
                )
        else:
            target = self._terminal_last_size or 420
            self.terminal_host.setVisible(True)
            self.right_splitter.setSizes(
                [max(sum(sizes) - target, 200), target]
            )
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.remove_chip("terminal")
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

    def _content_is_minimized(self) -> bool:
        """Upper area (workspace details + sessions) está minimizada?
        Agora minimiza igual aos runners (colapsa pra 0), então a única
        forma de restaurar é o chip da MinimizeTray."""
        sizes = self.right_splitter.sizes()
        if not sizes or len(sizes) < 2:
            return False
        return sizes[0] <= 4

    def _toggle_content_minimized(self) -> None:
        """Alterna entre upper minimizado e tamanho normal — mesmo
        padrão do runners e do terminal pane: colapsa pra 0 e adiciona
        chip na MinimizeTray. Restauração via clique no chip."""
        sizes = self.right_splitter.sizes()
        total = sum(sizes) or 800
        if not self._content_is_minimized():
            # Minimizar: guarda tamanho atual + colapsa pra 0
            self._content_last_size = sizes[0] if sizes[0] > 50 else 400
            self.content_stack.setVisible(False)
            self.right_splitter.setSizes([0, total])
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.add_chip(
                    "workspace", "Workspace", "fa5s.folder-open"
                )
        else:
            target = getattr(self, "_content_last_size", 400) or 400
            self.content_stack.setVisible(True)
            self.right_splitter.setSizes([target, max(total - target, 200)])
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.remove_chip("workspace")
        self._refresh_terminal_btns()
        # Atualiza o ícone do botão de minimize no header dos details
        if hasattr(self, "details"):
            self.details.refresh_minimize_btn(self._content_is_minimized())
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
        """Abre um agente novo no workspace selecionado. Tolera item-filho
        (sobe pro parent) e cai pro details.workspace como último recurso
        — botão ＋ da tab bar funciona mesmo sem seleção explícita na sidebar."""
        ws: Workspace | None = None
        current = self.list_widget.currentItem()
        if current is not None:
            # Bug antigo: data() de QTreeWidgetItem precisa de (col, role) —
            # `data(Qt.UserRole)` retorna o texto da coluna 0, não o ws.
            data = current.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Workspace):
                ws = data
            elif current.parent() is not None:
                pdata = current.parent().data(0, Qt.ItemDataRole.UserRole)
                if isinstance(pdata, Workspace):
                    ws = pdata
        if ws is None and self.details.workspace is not None:
            ws = self.details.workspace
        if ws is None:
            return
        self._show_ai_launch_menu(ws)

    def _toggle_right_dock(self) -> None:
        d = self.body_dock.dock("ferramentas")
        was_closed = d is not None and d.isClosed()
        self.body_dock.toggle("ferramentas")
        # Ao reexibir, garante que pelo menos um painel esteja aberto — senão
        # o dock volta como faixa de 36px e parece que "não abriu".
        if was_closed and not self.right_dock.open_panels():
            default_pid = next(
                (s.panel_id for s in self.DOCK_PANEL_SPECS if s.default_open),
                self.DOCK_PANEL_SPECS[0].panel_id if self.DOCK_PANEL_SPECS else None,
            )
            if default_pid is not None:
                self.right_dock.set_panel_open(default_pid, True)
        self._schedule_layout_save()

    def _install_ferramentas_minimize_btn(self) -> None:
        """Insere um botão '—' na title bar do dock Ferramentas que esconde o
        painel. Reusa o mesmo toggle do botão da topbar."""
        from .icons import ic as _ic

        area = self._right_panel_dock.dockAreaWidget()
        if area is None:
            return
        title_bar = area.titleBar()
        if title_bar is None:
            return
        btn = QPushButton(title_bar)
        btn.setIcon(_ic("fa5s.minus", color="#c8c8c8"))
        btn.setIconSize(QSize(13, 13))
        btn.setFlat(True)
        btn.setFixedSize(22, 22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Minimizar painel de ferramentas (Ctrl+Shift+B)")
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 3px; }"
            "QPushButton:hover { background: #2a2a2a; }"
        )
        btn.clicked.connect(self._toggle_right_dock)
        # Insere no fim do layout da title bar → fica no canto superior direito,
        # depois do stretch que separa as abas dos botões.
        title_bar.insertWidget(title_bar.layout().count(), btn)

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
            self.emit_workspace_error(
                "Falha ao abrir pasta",
                workspace_id=ws.id,
                body=str(e),
            )

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
            sessions = list_sessions_for_paths_backend(paths, backend=self.settings.ai_backend, limit=1)
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
    # Ordem visual no splitter: do topo pro fim segue a ordem desta lista.
    # Default: Git primeiro (topo, mais usado em PR/commit) → Skills →
    # Arquivos → Memória. Match com mockup que tem Git acima de tabs
    # Skills/Agents/Commands.
    DOCK_PANEL_SPECS: list[DockPanelSpec] = [
        DockPanelSpec(
            panel_id="git",
            title="Git",
            icon="⎇",
            factory=lambda mw: mw.details.git_panel(),
            default_open=True,
        ),
        DockPanelSpec(
            panel_id="skills",
            title="Skills",
            icon="✦",
            factory=lambda mw: SkillsPanel(settings=mw.settings),
            default_open=True,
        ),
        DockPanelSpec(
            panel_id="files",
            title="Arquivos",
            icon="📁",
            factory=lambda mw: mw._build_files_panel(),
            default_open=True,
        ),
        DockPanelSpec(
            panel_id="memory",
            title="Memória",
            icon="❏",
            factory=lambda mw: MemoryPanel(),
            default_open=False,
        ),
    ]

    def _build_files_panel(self) -> QWidget:
        """Factory pro FilesPanel no right dock. Duplo-click num arquivo
        abre como aba central (EditorTab dentro do _bottom_tabs)."""
        from .files_panel import FilesPanel
        panel = FilesPanel(settings=self.settings)
        panel.open_file_requested.connect(self._open_file_as_central_tab)
        return panel

    def _refresh_terminal_tabs_bar(self) -> None:
        """A tab bar do `_terminal_tabs` só aparece quando há mais que a
        aba 'Claude console' (i.e. quando o user abriu arquivos via
        FilesPanel — EditorTabs). Em workflow padrão fica escondida pra
        evitar redundância com o header workspace·console."""
        if not hasattr(self, "_terminal_tabs"):
            return
        self._terminal_tabs.tabBar().setVisible(
            self._terminal_tabs.count() > 1
        )

    def _on_central_tab_close(self, idx: int) -> None:
        """Fecha a aba SE for um EditorTab. Abas fixas (Claude console /
        Runners workspace / Runners console) ignoram o close request."""
        from .editor_tab import EditorTab
        w = self._bottom_tabs.widget(idx)
        if isinstance(w, EditorTab):
            self._bottom_tabs.removeTab(idx)
            w.deleteLater()
            self._refresh_terminal_tabs_bar()

    def _open_file_as_central_tab(self, abs_path: str) -> None:
        """Abre `abs_path` como nova aba no `_bottom_tabs`. Se já estiver
        aberto, só foca a aba existente (idempotente)."""
        from pathlib import Path

        from .editor_tab import EditorTab

        # Idempotente: se já está aberto, só foca
        for i in range(self._bottom_tabs.count()):
            w = self._bottom_tabs.widget(i)
            if isinstance(w, EditorTab) and w.path == abs_path:
                self._bottom_tabs.setCurrentIndex(i)
                return

        editor = EditorTab(abs_path)
        title = Path(abs_path).name

        from .icons import ic
        idx = self._bottom_tabs.addTab(editor, title)
        self._bottom_tabs.setTabIcon(idx, ic("fa5s.file-alt", color="#9aa0a6"))
        self._bottom_tabs.setTabToolTip(idx, abs_path)
        self._bottom_tabs.setCurrentIndex(idx)
        # Garante que tabsClosable está ON pra essa aba poder fechar
        self._bottom_tabs.setTabsClosable(True)
        self._refresh_terminal_tabs_bar()

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
        # Header "Terminal" com min/max/close era do pré-QtAds (controlava
        # o resize vertical do pane). Com QtAds o user redimensiona livre,
        # e o título "Terminal" duplica com a tab "Claude console" — sumir.
        self._terminal_header.setVisible(False)
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
        self.terminal_host.currentChanged.connect(
            lambda _i: self._refresh_terminal_pane_title()
        )

        # Embute o host num sub-splitter vertical: Claude console em cima
        # + Runners (workspace + console) embaixo (minimizável).
        pane = builder.pane
        layout = pane.layout()
        layout.removeWidget(self.terminal_host)

        from PySide6.QtWidgets import QSplitter as _QSp
        self._bottom_sub_splitter = _QSp(Qt.Orientation.Vertical)
        self._bottom_sub_splitter.setHandleWidth(SPLITTER_HANDLE_W)
        self._bottom_sub_splitter.setMinimumWidth(0)
        self._bottom_sub_splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3a3a3a; }"
        )

        # ----- Tabs do TERMINAL (só Claude console + EditorTabs) -----
        tabs_qss = (
            "QTabWidget::pane { border: 0; }"
            "QTabBar { background: #161616; }"
            "QTabBar::tab { background: #161616; color: #9aa0a6; "
            "  padding: 6px 14px; border: 0; "
            "  border-right: 1px solid #2a2a2a; min-height: 22px; }"
            "QTabBar::tab:selected { background: #181818; color: #e6e6e6; "
            "  border-bottom: 2px solid #5ac35a; }"
            "QTabBar::tab:hover:!selected { color: #c8c8c8; }"
        )
        self._terminal_tabs = QTabWidget(pane)
        self._terminal_tabs.setMinimumWidth(0)
        self._terminal_tabs.setDocumentMode(True)
        self._terminal_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._terminal_tabs.setStyleSheet(tabs_qss)
        # Tabs fixas (Claude console) não fecham; só EditorTabs abertas
        # via FilesPanel. Handler é _on_central_tab_close.
        self._terminal_tabs.tabCloseRequested.connect(self._on_central_tab_close)
        # Esconde a tab bar enquanto só existir a aba "Claude console"
        # — ela vira ruído já que o header logo acima mostra
        # workspace · console. Quando EditorTabs forem abertas via
        # FilesPanel (count > 1), a barra reaparece automaticamente
        # via `_refresh_terminal_tabs_bar`.
        self._terminal_tabs.tabBar().setVisible(False)

        from .icons import ICONS, ic
        idx_console = self._terminal_tabs.addTab(self.terminal_host, "Console IA")
        self._terminal_tabs.setTabIcon(idx_console, ic(ICONS["console"], color="#9aa0a6"))

        # Mantém alias _bottom_tabs apontando pro terminal_tabs pra evitar
        # quebrar callsites legados que assumiam um único QTabWidget. EditorTabs
        # abertas via FilesPanel vão pro terminal_tabs naturalmente.
        self._bottom_tabs = self._terminal_tabs

        # Container do terminal pane com header próprio (espelho do
        # runners pane logo abaixo). Header tem só um botão de
        # minimizar no canto direito — visual idêntico ao do runners.
        self._terminal_pane_widget = QWidget()
        self._terminal_pane_widget.setMinimumWidth(0)
        tp_layout = QVBoxLayout(self._terminal_pane_widget)
        tp_layout.setContentsMargins(0, 0, 0, 0)
        tp_layout.setSpacing(0)
        terminal_header = QWidget()
        terminal_header.setMinimumWidth(0)
        terminal_header.setStyleSheet(
            "background: #161616; border-bottom: 1px solid #2a2a2a;"
        )
        th_layout = QHBoxLayout(terminal_header)
        th_layout.setContentsMargins(10, 5, 4, 5)
        th_layout.setSpacing(8)
        # Label dinâmico: workspace + console ativo, ambos em destaque.
        # Substitui a tab bar interna do TerminalArea (que foi escondida)
        # — única fonte de "qual console estou olhando" agora é este header
        # + a seleção no sidebar (Sessões Claude).
        self._terminal_pane_title = QLabel("Console IA")
        self._terminal_pane_title.setTextFormat(Qt.TextFormat.RichText)
        self._terminal_pane_title.setStyleSheet(
            "color: #c8c8c8; font-size: 12px;"
        )
        # Branch longo no breadcrumb empurrava o sizeHint do label, forçando
        # a largura mínima do header → painel → dock central e disparando um
        # scroll horizontal que cortava a UI nos dois lados. wordWrap deixa
        # quebrar em 2+ linhas e a policy Ignored impede o label de exigir
        # mais largura que a disponível (ele se ajusta ao espaço, não o contrário).
        self._terminal_pane_title.setWordWrap(True)
        self._terminal_pane_title.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._terminal_pane_title.setMinimumWidth(0)
        th_layout.addWidget(self._terminal_pane_title, stretch=1)
        from PySide6.QtCore import QSize as _QS
        from PySide6.QtWidgets import QPushButton as _QPB2
        self._terminal_pane_minimize_btn = _QPB2()
        self._terminal_pane_minimize_btn.setIcon(
            ic("fa5s.window-minimize", color="#c8c8c8")
        )
        self._terminal_pane_minimize_btn.setIconSize(_QS(11, 11))
        self._terminal_pane_minimize_btn.setFixedSize(22, 20)
        self._terminal_pane_minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terminal_pane_minimize_btn.setToolTip("Minimizar terminal")
        self._terminal_pane_minimize_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 3px; }"
            "QPushButton:hover { background: #2a2a2a; }"
        )
        self._terminal_pane_minimize_btn.clicked.connect(
            self._toggle_terminal_pane_minimized
        )
        th_layout.addWidget(self._terminal_pane_minimize_btn)
        tp_layout.addWidget(terminal_header)
        tp_layout.addWidget(self._terminal_tabs, stretch=1)

        self._bottom_sub_splitter.addWidget(self._terminal_pane_widget)

        # ----- Panes dos RUNNERS (workspace e console, separados) -----
        # Cada um tem header + botão minimize próprio e ocupa entrada
        # independente no `_bottom_sub_splitter` — chip próprio na tray.
        self.runner_host = QStackedWidget()
        self.runner_host.setMinimumHeight(0)
        # RunnerArea propagaria mínimo de largura >600px (toolbar com ~8
        # botões) pra cima até a janela. Quebra aqui na fronteira do host.
        self.runner_host.setMinimumWidth(0)
        runner_empty = QLabel("Selecione um workspace para ver seus runners.")
        runner_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        runner_empty.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 28px;"
        )
        self._runner_placeholder_idx = self.runner_host.addWidget(runner_empty)

        self.console_runner_host = QStackedWidget()
        self.console_runner_host.setMinimumHeight(0)
        self.console_runner_host.setMinimumWidth(0)
        self._console_runner_placeholder_idx = self.console_runner_host.addWidget(
            self._build_console_runner_placeholder()
        )

        from PySide6.QtCore import QSize as _QS
        from PySide6.QtWidgets import QPushButton as _QPB

        def _build_pane(
            title: str, icon_name: str, body: QWidget, tooltip_min: str,
            on_click,
        ) -> tuple[QWidget, _QPB]:
            container = QWidget()
            container.setMinimumWidth(0)
            cl = QVBoxLayout(container)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            header = QWidget()
            header.setStyleSheet(
                "background: #161616; border-bottom: 1px solid #2a2a2a;"
            )
            hl = QHBoxLayout(header)
            hl.setContentsMargins(8, 3, 4, 3)
            hl.setSpacing(6)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(ic(icon_name, color="#9aa0a6").pixmap(_QS(12, 12)))
            hl.addWidget(icon_lbl)
            t_lbl = QLabel(title)
            t_lbl.setStyleSheet(
                "color: #c8c8c8; font-size: 11px; font-weight: 600;"
            )
            hl.addWidget(t_lbl)
            hl.addStretch(1)
            btn = _QPB()
            btn.setIcon(ic("fa5s.window-minimize", color="#c8c8c8"))
            btn.setIconSize(_QS(11, 11))
            btn.setFixedSize(22, 20)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip_min)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: 0; border-radius: 3px; }"
                "QPushButton:hover { background: #2a2a2a; }"
            )
            btn.clicked.connect(on_click)
            hl.addWidget(btn)
            cl.addWidget(header)
            cl.addWidget(body, stretch=1)
            return container, btn

        self._runners_pane, self._runners_minimize_btn = _build_pane(
            "Runners",
            ICONS["runners_workspace"],
            self.runner_host,
            "Minimizar área de runners",
            self._toggle_runners_minimized,
        )
        self._runners_console_pane, self._runners_console_minimize_btn = _build_pane(
            "Runners console",
            ICONS["runners_console"],
            self.console_runner_host,
            "Minimizar runners do console",
            self._toggle_runners_console_minimized,
        )

        self._bottom_sub_splitter.addWidget(self._runners_pane)
        self._bottom_sub_splitter.addWidget(self._runners_console_pane)
        self._runners_console_pane.hide()
        # Restaura sizes salvos. Default: terminal + runners; runners de
        # console não ocupam mais painel separado.
        # Migração: salvos com 2 entradas (legado terminal+runners combinados)
        # → divide a antiga entrada de runners ao meio.
        saved_sub = list(self.settings.bottom_sub_splitter_sizes or [])
        if len(saved_sub) == 3 and sum(saved_sub) > 0:
            self._bottom_sub_splitter.setSizes([saved_sub[0], saved_sub[1], 0])
        elif len(saved_sub) == 2 and sum(saved_sub) > 0:
            self._bottom_sub_splitter.setSizes([saved_sub[0], saved_sub[1], 0])
        else:
            self._bottom_sub_splitter.setSizes([700, 260, 0])

        layout.addWidget(self._bottom_sub_splitter, stretch=1)
        return pane

    def _build_console_runner_placeholder(self) -> QWidget:
        """Placeholder do pane 'Runners console' quando nenhum console está aberto.

        Mimetiza o header da RunnerArea (mesmos botões em mesma ordem) mas
        com tudo desabilitado e tooltip explicando que precisa abrir um
        console Claude primeiro. Visual fica consistente com o pane workspace.
        """
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)
        h.addWidget(QLabel("Runners (console)"))
        h.addStretch()

        hint = (
            "Abra um console Claude para criar runners específicos dele."
        )
        for text in (
            "▶ Rodar todos",
            "■ Parar todos",
            "✕ Remover todos",
            "Importar",
            "Exportar",
            "↗ Copiar do workspace",
            "↻ Recarregar runners",
            "+ Novo",
        ):
            btn = QPushButton(text)
            btn.setEnabled(False)
            btn.setToolTip(hint)
            h.addWidget(btn)
        outer.addWidget(header)

        body = QLabel(
            "Abra um console Claude e, na barra do terminal, clique em "
            "▤ Runners para criar runners específicos desse console."
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        body.setStyleSheet("background: #0e0e0e; color: #555; padding: 28px;")
        outer.addWidget(body, stretch=1)
        return container

    def _on_minimize_tray_restore(self, panel_id: str) -> None:
        """Click num chip da MinimizeTray → restaura o painel correspondente."""
        if panel_id == "workspace":
            if self._content_is_minimized():
                self._toggle_content_minimized()
        elif panel_id == "runners":
            if self._runners_pane_is_minimized():
                self._toggle_runners_minimized()
        elif panel_id == "runners_console":
            self._minimize_tray.remove_chip("runners_console")
        elif panel_id == "terminal_pane":
            if self._terminal_pane_is_minimized():
                self._toggle_terminal_pane_minimized()
        elif panel_id == "terminal":
            if self._terminal_is_minimized():
                self._toggle_terminal()

    def _runners_pane_is_minimized(self) -> bool:
        sizes = (
            self._bottom_sub_splitter.sizes()
            if hasattr(self, "_bottom_sub_splitter")
            else []
        )
        return len(sizes) >= 3 and sizes[1] <= 4

    def _runners_console_pane_is_minimized(self) -> bool:
        return True

    def _terminal_pane_is_minimized(self) -> bool:
        sizes = (
            self._bottom_sub_splitter.sizes()
            if hasattr(self, "_bottom_sub_splitter")
            else []
        )
        return len(sizes) >= 3 and sizes[0] <= 4

    def _toggle_pane_at(
        self,
        idx: int,
        pane_widget: QWidget,
        btn,
        chip_id: str,
        chip_label: str,
        chip_icon: str,
        tooltip_min: str,
        tooltip_max: str,
        last_size_attr: str,
        default_size: int,
    ) -> None:
        """Colapsa/restaura uma entrada do `_bottom_sub_splitter`.

        Generaliza o min/max — funciona pra terminal (idx=0),
        runners workspace (idx=1) e runners console (idx=2)."""
        sizes = self._bottom_sub_splitter.sizes()
        if len(sizes) < 3 or idx >= len(sizes):
            return
        total = sum(sizes)
        from PySide6.QtCore import QSize as _QS

        from .icons import ic
        if sizes[idx] > 4:
            # Minimizar — guarda o tamanho atual + colapsa só essa entrada
            setattr(self, last_size_attr, sizes[idx])
            pane_widget.setVisible(False)
            new_sizes = list(sizes)
            freed = new_sizes[idx]
            new_sizes[idx] = 0
            # Redistribui o espaço liberado nas demais entradas, na
            # proporção do tamanho atual delas (mantém ratio entre os
            # panes que sobraram). Se todas as outras estão zeradas,
            # joga tudo no terminal (idx 0) como fallback razoável.
            others_total = sum(s for i, s in enumerate(new_sizes) if i != idx)
            if others_total > 0:
                for i in range(len(new_sizes)):
                    if i == idx:
                        continue
                    new_sizes[i] += int(freed * (new_sizes[i] / others_total))
            else:
                new_sizes[0] = total
            self._bottom_sub_splitter.setSizes(new_sizes)
            btn.setIcon(ic("fa5s.window-maximize", color="#c8c8c8"))
            btn.setIconSize(_QS(11, 11))
            btn.setToolTip(tooltip_max)
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.add_chip(chip_id, chip_label, chip_icon)
        else:
            target = getattr(self, last_size_attr, default_size) or default_size
            pane_widget.setVisible(True)
            # Tira proporcional dos outros panes pra abrir espaço.
            others_total = sum(s for i, s in enumerate(sizes) if i != idx)
            new_sizes = list(sizes)
            if others_total > 0 and target < others_total:
                scale = (others_total - target) / others_total
                for i in range(len(new_sizes)):
                    if i == idx:
                        continue
                    new_sizes[i] = max(int(new_sizes[i] * scale), 0)
                new_sizes[idx] = target
            else:
                # Fallback: pega 1/3 do total
                each = max(total // 3, 100)
                new_sizes = [each] * 3
                new_sizes[idx] = max(target, each)
            self._bottom_sub_splitter.setSizes(new_sizes)
            btn.setIcon(ic("fa5s.window-minimize", color="#c8c8c8"))
            btn.setIconSize(_QS(11, 11))
            btn.setToolTip(tooltip_min)
            if hasattr(self, "_minimize_tray"):
                self._minimize_tray.remove_chip(chip_id)
        self._schedule_layout_save()

    def _toggle_terminal_pane_minimized(self) -> None:
        self._toggle_pane_at(
            0,
            self._terminal_pane_widget,
            self._terminal_pane_minimize_btn,
            "terminal_pane",
            "Terminal",
            "fa5s.terminal",
            "Minimizar terminal",
            "Restaurar terminal",
            "_terminal_pane_last_size",
            600,
        )

    def _toggle_runners_minimized(self) -> None:
        self._toggle_pane_at(
            1,
            self._runners_pane,
            self._runners_minimize_btn,
            "runners",
            "Runners",
            "mdi6.source-branch",
            "Minimizar área de runners",
            "Restaurar área de runners",
            "_runners_last_size",
            200,
        )

    def _toggle_runners_console_minimized(self) -> None:
        if hasattr(self, "_minimize_tray"):
            self._minimize_tray.remove_chip("runners_console")
        self._runners_console_pane.hide()

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
        self._minimized_ws_tray = builder.minimized_tray
        self._minimized_ws_tray.restore_requested.connect(
            self._on_minimized_workspace_restore
        )
        self.list_widget = builder.list_widget
        self.version_label = builder.version_label
        self._context_status_label = builder.context_status_label
        self._context_status_container = builder.context_status_container
        self._context_status_refresh_btn = builder.context_status_refresh_btn
        self._context_status_refresh_btn.clicked.connect(
            self._on_context_status_refresh_clicked
        )
        self._context_status_updated_label = builder.context_status_updated_label
        self._set_console_runners_footer = builder.set_console_runners
        builder.console_runner_requested.connect(self._open_footer_runner)
        builder.runner_toggle_requested.connect(self._toggle_runner_from_sidebar)
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
            # Terminais vivem no bucket "Sessões Claude" — usa o iterator.
            for child in self._iter_terminal_items(ws_item):
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
            widget.set_expanded_visual(not collapsed)
        elif isinstance(widget, RunnerGroupWidget):
            widget.set_collapsed(collapsed)

    def _toggle_pin_workspace(self, ws: "Workspace") -> None:
        """Inverte ws.pinned e re-renderiza a sidebar (refresh_list é
        disparado via workspaces_coord.workspaces_changed)."""
        self.workspaces_coord.set_pinned(ws.id, not ws.pinned)

    def _minimize_workspace(self, ws: "Workspace") -> None:
        """Tira o workspace da lista da sidebar; ele vira um chip na faixa
        'Minimizados' no rodapé. Restauração via clique no chip."""
        self.workspaces_coord.set_minimized(ws.id, True)

    def _on_minimized_workspace_restore(self, workspace_id: str) -> None:
        """Click no chip da faixa 'Minimizados' → workspace volta pra lista."""
        if self.workspaces_coord.set_minimized(workspace_id, False):
            item = self._find_workspace_item(workspace_id)
            if item is not None:
                self.list_widget.setCurrentItem(item)

    def _refresh_minimized_tray(self) -> None:
        """Sincroniza os chips da faixa 'Minimizados' com os workspaces que
        têm minimized=True. Idempotente — chamado em todo refresh_list."""
        tray = getattr(self, "_minimized_ws_tray", None)
        if tray is None:
            return
        minimized = {ws.id: ws for ws in self.workspaces if ws.minimized}
        # Remove chips de workspaces que não estão mais minimizados/existem.
        for chip_id in list(tray._chips.keys()):
            if chip_id not in minimized:
                tray.remove_chip(chip_id)
        # Adiciona/atualiza chips dos minimizados (add_chip é idempotente).
        for ws_id, ws in minimized.items():
            if not tray.has_chip(ws_id):
                tray.add_chip(ws_id, ws.name, "fa5s.folder")

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
                continue_act.setToolTip("Manda 'continue' + Enter pro agente desta aba")
                continue_act.triggered.connect(term.send_continue)
                menu.addAction(continue_act)
                menu.addSeparator()
                cycle_act = QAction("↹ Ciclar modo (Plan / Auto / …)", menu)
                cycle_act.setToolTip(
                    "Manda Shift+Tab pro agente — cicla entre Plan, Auto-accept "
                    "e Default. Olha o indicador embaixo-direita do TUI pra ver "
                    "onde parou."
                )
                cycle_act.triggered.connect(term.send_cycle_mode)
                menu.addAction(cycle_act)
                effort_act = QAction("⏻ Trocar effort (/effort)", menu)
                effort_act.setToolTip("Abre o slash command /effort no prompt do agente")
                effort_act.triggered.connect(term.send_open_effort)
                menu.addAction(effort_act)
                model_act = QAction("✦ Trocar modelo (/model)", menu)
                model_act.setToolTip("Abre o slash command /model no prompt do agente")
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
            min_act = QAction("— Minimizar workspace", menu)
            min_act.setToolTip(
                "Remove o workspace da lista; vira um chip em 'Minimizados' "
                "no rodapé. Clique no chip pra restaurar."
            )
            min_act.triggered.connect(lambda _c=False, w=ws: self._minimize_workspace(w))
            menu.addAction(min_act)
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
                    f"Manda 'continue' pra {count} console(s) de IA rodando neste workspace"
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

        # Workspaces minimizados saem da lista e viram chips na faixa
        # "Minimizados" no rodapé da sidebar.
        self._refresh_minimized_tray()

        # Particiona: workspaces fixados aparecem em "FIXADOS" no topo,
        # fora da lista principal (não duplica). Minimizados ficam fora
        # de ambas as seções (só viram chip).
        visible = [ws for ws in self.workspaces if not ws.minimized]
        pinned = [ws for ws in visible if ws.pinned]
        regular = [ws for ws in visible if not ws.pinned]

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

        # Reaplica colapso das seções DEPOIS de popular — no add_header
        # original a tree ainda não tinha os items abaixo, então o
        # esconder não pegava nada.
        for _label in ("FIXADOS", "WORKSPACES"):
            if bool(self.settings.section_collapsed.get(_label, False)):
                self._apply_section_collapse(_label, True)

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
                # Terminais agora vivem dentro do bucket Sessões Claude —
                # desce um nível pra achar os tab_ids.
                for term_item in self._iter_terminal_items(it):
                    tab_id = term_item.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(tab_id, int):
                        self._install_console_runner_children(term_item, ws_data, tab_id)
                self._refresh_sessoes_count(it)
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
        self._update_status_bar(None)
        if hasattr(self, "notif_service"):
            self._refresh_unread_badges()

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
        # Atualiza o status dot no header do painel de detalhes se
        # estamos olhando este workspace.
        if self.details.workspace and self.details.workspace.id == ws.id:
            self.details.set_active_status(count > 0)
            self._update_status_bar(ws)

    def _maybe_emit_cost_warning(self, snap) -> None:
        """Olha o snapshot do plan_usage_api e emite cost_warning quando
        uma janela cruza 80% (high) ou 95% (critical). Dedup por janela —
        a mesma janela só re-notifica depois do cooldown do service ou
        quando passa de high pra critical."""
        thresholds = [
            ("5h", getattr(snap, "five_hour", None)),
            ("7d", getattr(snap, "seven_day", None)),
            ("7d-sonnet", getattr(snap, "seven_day_sonnet", None)),
        ]
        for window_label, window in thresholds:
            if window is None:
                continue
            pct = float(getattr(window, "utilization_pct", 0) or 0)
            if pct < 80.0:
                continue
            priority = (
                NotificationPriority.CRITICAL if pct >= 95.0
                else NotificationPriority.HIGH
            )
            level = "crítico" if pct >= 95.0 else "alto"
            self.notif_service.notify(
                NotificationKind.COST_WARNING,
                title=f"💰 Uso do plano {level} — janela {window_label}",
                body=f"{pct:.0f}% consumido na janela {window_label}.",
                priority=priority,
                dedup_key=f"cost_warning:{window_label}:{level}",
                data={"window": window_label, "percent": pct},
            )

    def emit_workspace_error(
        self,
        message: str,
        *,
        workspace_id: str | None = None,
        body: str = "",
        critical: bool = False,
    ) -> None:
        """Helper público pra qualquer callsite emitir um erro de workspace
        como notificação. Usado por handlers de launch/git/etc. Centralizado
        aqui pra evitar que cada caller tenha que conhecer o service."""
        ws = self.workspaces_coord.find_by_id(workspace_id) if workspace_id else None
        ws_name = ws.name if ws else "Workspace"
        self.notif_service.notify(
            NotificationKind.WORKSPACE_ERROR,
            title=f"⚠ {message} — {ws_name}" if workspace_id else f"⚠ {message}",
            body=body,
            workspace_id=workspace_id,
            priority=NotificationPriority.CRITICAL if critical else NotificationPriority.HIGH,
        )

    def _on_tab_session_exited(
        self, tab_id: int, exit_code: int, workspace_id: str
    ) -> None:
        """PTY de um console terminou. Emite task_completed (exit=0) ou
        task_failed (exit>0). exit_code=-1 = indeterminado; tratamos como
        completed pra não criar alarme falso (KDE Wayland às vezes não
        consegue reapear o filho a tempo)."""
        # Limpa o tracking de long_running pra esse tab — não faz sentido
        # alertar "execução longa" de algo que já acabou.
        self._working_since.pop(tab_id, None)
        self._long_running_notified.discard(tab_id)

        ws = self.workspaces_coord.find_by_id(workspace_id) if workspace_id else None
        ws_name = ws.name if ws else "Workspace"
        # Tenta achar session_id atual do widget (claimed_session_id).
        session_id: str | None = None
        title = "Console"
        area = self.terminals_coord.area_for(workspace_id) if workspace_id else None
        if area is not None:
            for i in range(area.tabs.count()):
                w = area.tabs.widget(i)
                if id(w) == tab_id and isinstance(w, TerminalWidget):
                    session_id = w.claimed_session_id()
                    title = w.effective_title() if hasattr(w, "effective_title") else title
                    break

        # Exit codes > 128 vêm de sinal (128 + signum): 143=SIGTERM, 130=SIGINT,
        # 137=SIGKILL etc. Isso é terminação externa (app reiniciou, usuário
        # fechou aba, kill manual) — NÃO é falha de task. Suprime silenciosamente
        # pra evitar falso positivo a cada restart do app.
        if exit_code > 128:
            log.debug(
                "session exit por sinal (exit=%s tab=%s) — sem notificação",
                exit_code, tab_id,
            )
            return

        if exit_code <= 0:
            # Sucesso (ou indeterminado). Notif baixa prioridade.
            self.notif_service.notify(
                NotificationKind.TASK_COMPLETED,
                title=f"✓ Sessão encerrada — {ws_name}",
                body=f"{title}\nProcesso saiu com exit code {exit_code}.",
                workspace_id=workspace_id or None,
                session_id=session_id,
                tab_id=tab_id,
                data={"exit_code": exit_code},
            )
        else:
            self.notif_service.notify(
                NotificationKind.TASK_FAILED,
                title=f"✗ Sessão falhou — {ws_name}",
                body=f"{title}\nProcesso saiu com exit code {exit_code}.",
                workspace_id=workspace_id or None,
                session_id=session_id,
                tab_id=tab_id,
                data={"exit_code": exit_code},
            )

    def _scan_long_running(self) -> None:
        """Escaneia tabs em "working" e emite `long_running` ao passar do
        threshold (5min). Idempotente por tab — não re-emite até o tab sair
        de working e voltar."""
        if not self._working_since:
            return
        import time as _t
        now = _t.monotonic()
        threshold = 5 * 60  # 5min — futuro: settings.long_running_seconds
        for tab_id, started in list(self._working_since.items()):
            if tab_id in self._long_running_notified:
                continue
            if (now - started) < threshold:
                continue
            self._long_running_notified.add(tab_id)
            activity = self.terminals_coord.state.activity.get(tab_id)
            title_str = activity[2] if activity else "Console"
            ws_id = self.terminals_coord.state.tab_workspaces.get(tab_id)
            ws = self.workspaces_coord.find_by_id(ws_id) if ws_id else None
            ws_name = ws.name if ws else "Workspace"
            elapsed_min = int((now - started) // 60)
            self.notif_service.notify(
                NotificationKind.LONG_RUNNING,
                title=f"⏱ Execução longa — {ws_name}",
                body=f"{title_str}\nRodando há {elapsed_min} min.",
                workspace_id=ws_id,
                tab_id=tab_id,
                data={"elapsed_seconds": int(now - started)},
            )

    def _refresh_unread_badges(self) -> None:
        """Re-pinta badges em workspaces (laranja na sidebar) e nas sessões
        Claude (laranja no TerminalChildWidget) com base no service."""
        from .workspace_item_widget import WorkspaceItemWidget
        ws_counts = self.notif_service.unread_by_workspace()
        for ws in self.workspaces_coord.workspaces:
            item = self._find_workspace_item(ws.id)
            if item is None:
                continue
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, WorkspaceItemWidget):
                widget.set_unread_count(ws_counts.get(ws.id, 0))
        # Badge por sessão: chave do service.unread_by_session é session_id;
        # nas notifs do inbox_alert também guardamos tab_id, então fazemos
        # o fallback por tab_id pra casos onde session_id não foi setado.
        sess_counts = self.notif_service.unread_by_session()
        tab_counts: dict[int, int] = {}
        for n in self.notif_service.list(only_unseen=True):
            if n.tab_id is not None:
                tab_counts[n.tab_id] = tab_counts.get(n.tab_id, 0) + 1
        for tab_id, tree_item in self.terminals_coord.state.tree_items.items():
            widget = self.list_widget.itemWidget(tree_item, 0)
            if not isinstance(widget, TerminalChildWidget):
                continue
            sid = widget.claimed_session_id() if hasattr(widget, "claimed_session_id") else None
            count = sess_counts.get(sid, 0) if sid else 0
            count = max(count, tab_counts.get(tab_id, 0))
            widget.set_unread_count(count)

    def _focus_active_workspace_from_status(self) -> None:
        """Click no segmento 'workspace' do footer → ativa view de
        workspaces, scrolla pro workspace selecionado na sidebar e foca."""
        ws = self._current_workspace()
        if ws is None:
            return
        self.main_stack.setCurrentWidget(self.body_view)
        self.activity_bar.set_active(VIEW_WORKSPACES)
        self.content_stack.setCurrentIndex(0)
        item = self._find_workspace_item(ws.id)
        if item is not None:
            self.list_widget.setCurrentItem(item)
            self.list_widget.scrollToItem(item)
            self.list_widget.setFocus()

    def _focus_active_console_from_status(self) -> None:
        """Click no segmento de console do footer → foca a aba do
        terminal selecionado e seu pane (restaura se minimizado)."""
        item = self.list_widget.currentItem()
        if item is None:
            return
        tab_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(tab_id, int):
            return
        parent = item.parent()
        if parent is None:
            return
        ws = parent.data(0, Qt.ItemDataRole.UserRole)
        # Sobe parents até achar o workspace (consoles podem estar
        # aninhados no bucket "Sessões Claude").
        while parent is not None and not isinstance(ws, Workspace):
            parent = parent.parent()
            if parent is not None:
                ws = parent.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(ws, Workspace):
            return
        self._focus_terminal_tab(ws, tab_id)

    def _refresh_status_bar_console(self) -> None:
        """Sincroniza os segmentos de console do footer com o item
        selecionado atualmente na sidebar. Se o item selecionado não é
        um console (ou nada selecionado), oculta os segmentos."""
        if not hasattr(self, "status_widgets"):
            return
        item = self.list_widget.currentItem()
        widget = self.list_widget.itemWidget(item, 0) if item is not None else None
        if isinstance(widget, TerminalChildWidget):
            try:
                info = widget.status_info()
            except Exception:
                info = None
            self.status_widgets.set_console_info(info)
        else:
            self.status_widgets.set_console_info(None)

    def _update_status_bar(self, ws: "Workspace | None") -> None:
        # Top bar chip de workspace ativo (proeminente, ao lado do logo)
        if hasattr(self, "top_bar"):
            self.top_bar.set_active_workspace(ws.name if ws else None)

        """Atualiza os segmentos da QStatusBar. Pode receber None pra
        zerar (workspace vazio)."""
        if not hasattr(self, "status_widgets"):
            return
        if ws is None:
            self.status_widgets.set_workspace(None)
            self.status_widgets.set_stack("")
            self.status_widgets.set_mcp(0)
            self.status_widgets.set_runners(0, 0)
            self.status_widgets.set_task("Nenhuma tarefa em execução")
            return
        self.status_widgets.set_workspace(ws.name)
        # Stack
        from ..stacks import STACK_LABEL, detect_stacks
        stacks = detect_stacks(ws.folders)
        stack_label = ", ".join(sorted(STACK_LABEL.get(s, s) for s in stacks))
        self.status_widgets.set_stack(stack_label)
        # MCP — lista real (user globais + .mcp.json do projeto), igual ao
        # que o Claude enxerga e à barra de contexto do console. Passa os
        # nomes pro footer mostrar inline + tooltip.
        try:
            from ..services.mcp_inspector import SCOPE_PROJECT, list_servers
            mcp_names = sorted({
                s.name for s in list_servers(list(ws.folders))
                if s.scope == SCOPE_PROJECT
            })
        except Exception:
            mcp_names = []
        self.status_widgets.set_mcp(len(mcp_names), mcp_names)
        # Runners
        active = self.terminals_coord.state.running_counts.get(ws.id, 0)
        total = len(ws.runners)
        self.status_widgets.set_runners(active, total)
        # Tarefa atual — placeholder simples (Fase 4 polimento depois)
        if active > 0:
            self.status_widgets.set_task(f"{active} console(s) Claude ativos", working=True)
        else:
            self.status_widgets.set_task("Nenhuma tarefa em execução")

    _SECTION_HEADER_ROLE = "__section_header__"
    # Sub-role pra guardar o label da seção (FIXADOS / WORKSPACES) no
    # próprio item — usado pra resolver clique → toggle de colapso.
    _SECTION_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1

    _SECTION_ICONS = {
        "FIXADOS": "fa5s.thumbtack",
        "WORKSPACES": "fa5s.layer-group",
    }

    def _add_section_header(self, label: str) -> None:
        """Insere um item-cabeçalho clicável (FIXADOS / WORKSPACES).

        Clicar no header alterna o colapso da seção (esconde/mostra os
        workspaces até o próximo header). Estado persiste em
        `settings.section_collapsed`.

        Usa setText/setIcon nativos do QTreeWidgetItem (em vez de
        setItemWidget) — o widget custom sofria clipping pela largura
        da coluna do tree e cortava o "S" final. Native respeita o
        sizeHint do delegate."""
        from PySide6.QtCore import QSize as _QS
        from PySide6.QtGui import QBrush, QColor, QFont

        collapsed = bool(self.settings.section_collapsed.get(label, False))
        chevron = "▸" if collapsed else "▾"
        item = QTreeWidgetItem([f"{chevron} {label}"])
        item.setData(0, Qt.ItemDataRole.UserRole, self._SECTION_HEADER_ROLE)
        item.setData(0, self._SECTION_LABEL_ROLE, label)
        # Enabled mas não-selecionável: precisa de ItemIsEnabled pra
        # disparar itemClicked; sem ItemIsSelectable pro highlight
        # azul/seleção não aparecer.
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        # Sem ícone — fica mais à esquerda (o ícone adicionava offset
        # nativo do QTreeWidgetItem). Chevron já indica seção colapsável.
        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        item.setFont(0, font)
        item.setForeground(0, QBrush(QColor("#a8a8a8")))
        item.setSizeHint(0, _QS(0, 20))
        self.list_widget.addTopLevelItem(item)
        # Aplica o colapso restaurado imediatamente — esconde os
        # workspaces da seção se já estava colapsada antes.
        if collapsed:
            self._apply_section_collapse(label, True)

    def _items_in_section(self, label: str) -> list["QTreeWidgetItem"]:
        """Lista top-level items que pertencem à seção `label`
        (entre o header `label` e o próximo header, ou fim da tree)."""
        items: list[QTreeWidgetItem] = []
        n = self.list_widget.topLevelItemCount()
        i = 0
        while i < n:
            it = self.list_widget.topLevelItem(i)
            if (
                it.data(0, Qt.ItemDataRole.UserRole) == self._SECTION_HEADER_ROLE
                and it.data(0, self._SECTION_LABEL_ROLE) == label
            ):
                j = i + 1
                while j < n:
                    nxt = self.list_widget.topLevelItem(j)
                    if nxt.data(0, Qt.ItemDataRole.UserRole) == self._SECTION_HEADER_ROLE:
                        break
                    items.append(nxt)
                    j += 1
                break
            i += 1
        return items

    def _apply_section_collapse(self, label: str, collapsed: bool) -> None:
        """Esconde/mostra os workspaces da seção e atualiza o chevron
        do header."""
        for top in self._items_in_section(label):
            top.setHidden(collapsed)
        # Atualiza chevron no texto do header
        for i in range(self.list_widget.topLevelItemCount()):
            it = self.list_widget.topLevelItem(i)
            if (
                it.data(0, Qt.ItemDataRole.UserRole) == self._SECTION_HEADER_ROLE
                and it.data(0, self._SECTION_LABEL_ROLE) == label
            ):
                chevron = "▸" if collapsed else "▾"
                it.setText(0, f"{chevron} {label}")
                break

    def _toggle_section_collapsed(self, label: str) -> None:
        """Toggle do estado de colapso da seção (FIXADOS / WORKSPACES).
        Persiste em settings."""
        current = bool(self.settings.section_collapsed.get(label, False))
        new_state = not current
        self.settings.section_collapsed[label] = new_state
        self._apply_section_collapse(label, new_state)
        try:
            self.settings.save()
        except OSError:
            pass

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
            self._show_ai_launch_menu(ws)

        def on_toggle() -> None:
            item.setExpanded(not item.isExpanded())
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, WorkspaceItemWidget):
                widget.set_collapsed(not item.isExpanded())
                widget.set_expanded_visual(item.isExpanded())

        def on_toggle_pin() -> None:
            self._toggle_pin_workspace(ws)

        def on_minimize() -> None:
            self._minimize_workspace(ws)

        from PySide6.QtCore import QSize as _QS

        widget = WorkspaceItemWidget(
            ws.name, on_add, on_toggle, on_toggle_pin, on_minimize
        )
        widget.set_collapsed(not item.isExpanded())
        widget.set_expanded_visual(item.isExpanded())
        widget.set_pinned(ws.pinned)
        widget.set_running_count(
            self.terminals_coord.state.running_counts.get(ws.id, 0)
        )
        # Inicializa seleção pra refletir o ws atualmente selecionado —
        # rebuilds da árvore preservam o highlight branco no item certo.
        current_ws = self._current_workspace()
        widget.set_selected(current_ws is not None and current_ws.id == ws.id)
        item.setSizeHint(0, _QS(0, 36))
        self.list_widget.setItemWidget(item, 0, widget)
        self._refresh_empty_placeholder(item)

    _EMPTY_PLACEHOLDER_ROLE = "__empty_workspace_placeholder__"
    _BUCKET_ROLE = "__bucket__"
    _SESSOES_BUCKET_ROLE = "__bucket_sessoes__"

    def _ensure_sessoes_bucket(self, ws_item: "QTreeWidgetItem") -> "QTreeWidgetItem":
        """Devolve o bucket 'Sessões Claude (N)' do workspace, criando
        se ainda não existe. Posiciona depois do runner_group (que fica
        no topo) e antes do placeholder/outros."""
        from PySide6.QtCore import QSize as _QS

        # Procura existente
        for i in range(ws_item.childCount()):
            c = ws_item.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole) == self._SESSOES_BUCKET_ROLE:
                return c
        # Cria — bucket sem header visível: altura 0, sempre expandido.
        # Consoles ficam como filhos diretos visuais do workspace.
        bucket = QTreeWidgetItem()
        bucket.setData(0, Qt.ItemDataRole.UserRole, self._SESSOES_BUCKET_ROLE)
        bucket.setSizeHint(0, _QS(0, 0))
        ws_item.addChild(bucket)
        bucket.setExpanded(True)
        return bucket

    def _iter_terminal_items(self, ws_item: "QTreeWidgetItem"):
        """Itera os QTreeWidgetItem dos consoles dentro do bucket Sessões
        Claude. Generator pra simplificar todos os call sites antigos que
        faziam `ws_item.child(i)` assumindo terminais como filhos diretos."""
        for i in range(ws_item.childCount()):
            c = ws_item.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole) != self._SESSOES_BUCKET_ROLE:
                continue
            for j in range(c.childCount()):
                yield c.child(j)

    def _refresh_sessoes_count(self, ws_item: "QTreeWidgetItem") -> None:
        """Atualiza o badge de contagem do bucket Sessões Claude. Se 0, esconde o bucket."""
        bucket = None
        for i in range(ws_item.childCount()):
            c = ws_item.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole) == self._SESSOES_BUCKET_ROLE:
                bucket = c
                break
        if bucket is None:
            return
        count = bucket.childCount()
        bucket.setHidden(count == 0)
        host = self.list_widget.itemWidget(bucket, 0)
        if host is not None:
            count_lbl = host.property("_count_lbl")
            if count_lbl is not None:
                count_lbl.setText(str(count))

    def _install_arquivos_bucket(self, ws_item: "QTreeWidgetItem", ws: Workspace) -> None:
        """Cria item 'Arquivos' como primeiro filho do workspace. Clicar
        abre o file finder filtrando pelas pastas do workspace.

        Marcado com `_BUCKET_ROLE` pra iteradores que checam Workspace/int
        já filtrarem naturalmente (esses já fazem isinstance check antes
        de processar)."""
        from PySide6.QtCore import QSize as _QS
        from PySide6.QtWidgets import QPushButton as _QPB

        from .icons import ICONS
        from .icons import ic as _ic

        # Idempotente: se já existe em qualquer posição, só remove e
        # re-insere no topo (Runner group é inserido em 0 depois e
        # empurraria nosso bucket pra baixo).
        for i in range(ws_item.childCount()):
            c = ws_item.child(i)
            if c.data(0, Qt.ItemDataRole.UserRole) == self._BUCKET_ROLE:
                ws_item.takeChild(i)
                break

        bucket = QTreeWidgetItem()
        bucket.setData(0, Qt.ItemDataRole.UserRole, self._BUCKET_ROLE)
        bucket.setSizeHint(0, _QS(0, 26))
        ws_item.insertChild(0, bucket)

        btn = _QPB("  Arquivos")
        btn.setIcon(_ic(ICONS["folder"], color="#9aa0a6"))
        btn.setIconSize(_QS(13, 13))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Buscar arquivos neste workspace (Ctrl+P)")
        btn.setStyleSheet(
            "QPushButton { background: transparent; color: #c8c8c8; "
            "border: 0; text-align: left; padding: 3px 6px; font-size: 12px; }"
            "QPushButton:hover { color: #fff; background: #1f1f1f; "
            "border-radius: 3px; }"
        )

        def _open_files(_=False, w=ws):
            # Foca o workspace antes (file finder lê o current_workspace).
            self.list_widget.setCurrentItem(ws_item)
            self._open_file_finder_dialog("")

        btn.clicked.connect(_open_files)
        self.list_widget.setItemWidget(bucket, 0, btn)

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
            role = child.data(0, Qt.ItemDataRole.UserRole)
            if role == self._EMPTY_PLACEHOLDER_ROLE:
                placeholder_idx = i
            elif role == self._BUCKET_ROLE:
                # Bucket 'Arquivos' não conta como conteúdo real do ws —
                # o placeholder 'Nova sessão' continua aparecendo quando
                # não há consoles/runners.
                pass
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
        btn = QPushButton("＋  Nova sessão…")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(24)
        btn.setToolTip(
            "Escolha Claude ou OpenCode para abrir neste workspace (mesma ação do botão + "
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
        btn.clicked.connect(lambda: self._show_ai_launch_menu(ws))
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

        # Remove rows antigos de runners workspace-scope. Limpa direto pelo
        # parent em vez de iterar `_runner_tree_items[ws.id]` — esse dict
        # pode ficar fora de fase (item removido do dict mas ainda na tree,
        # ou vice-versa) e causa duplicação ao re-instalar. Pega tudo que
        # estiver pendurado no group antigo + qualquer runner-row solto
        # direto sob ws_item (layout pré-grupo).
        group_old = self._runner_group_items.get(ws.id)
        if group_old is not None:
            while group_old.childCount() > 0:
                group_old.removeChild(group_old.child(0))
        for i in range(ws_item.childCount() - 1, -1, -1):
            child_item = ws_item.child(i)
            data = child_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data and data[0] == "runner":
                ws_item.removeChild(child_item)
        self._runner_tree_items[ws.id] = {}

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
                "Runners",
                on_toggle_collapse=_toggle,
                on_stop_all=lambda _c=False, w=ws: self._stop_all_workspace_runners(w),
                on_restart_all=lambda _c=False, w=ws: self._restart_all_workspace_runners(w),
                on_run_all=lambda _c=False, w=ws: self._run_all_workspace_runners(w),
            )
            self.list_widget.setItemWidget(group, 0, header)
            collapsed = bool(
                self.settings.runner_group_collapsed.get(ws.id, False)
            )
            group.setExpanded(not collapsed)
            header.set_collapsed(collapsed)
            self._runner_group_items[ws.id] = group
            # Runner group oculto na sidebar — runners acessíveis via painel Runners.
            group.setHidden(True)

        # Atualiza badge sempre — header pode existir desde refresh anterior.
        existing_header = self.list_widget.itemWidget(group, 0)
        if isinstance(existing_header, RunnerGroupWidget):
            existing_header.set_count(len(scoped))
            existing_header.set_running_count(self._running_runner_count(ws.id))

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
        """Remove a antiga seção visual de runners por console da sidebar."""
        gk = (ws.id, tab_id)
        group_old = self._console_runner_group_items.get(gk)
        if group_old is not None:
            while group_old.childCount() > 0:
                child_item = group_old.child(0)
                data = child_item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, tuple) and len(data) >= 3:
                    self._runner_tree_items.get(ws.id, {}).pop(data[2], None)
                group_old.removeChild(child_item)
            term_item.removeChild(group_old)
            self._console_runner_group_items.pop(gk, None)
        for i in range(term_item.childCount() - 1, -1, -1):
            child_item = term_item.child(i)
            data = child_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data and data[0] == "runner":
                if len(data) >= 3:
                    self._runner_tree_items.get(ws.id, {}).pop(data[2], None)
                term_item.removeChild(child_item)
        return

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
        # Cada console também tem seus runners — refaz para todos
        # (consoles vivem no bucket Sessões Claude).
        for sib in self._iter_terminal_items(ws_item):
            tab_id = sib.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(tab_id, int):
                self._install_console_runner_children(sib, ws, tab_id)

    def _running_runner_count(self, workspace_id: str) -> int:
        """Quantos runners do workspace estão rodando agora — usado
        pra alimentar o badge verde no header do grupo Runners."""
        area = self._runner_areas.get(workspace_id)
        if area is None:
            return 0
        from .runner_area import RunnerWidget

        count = 0
        for i in range(area.tabs.count()):
            w = area.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.is_running():
                count += 1
        return count

    def _update_runner_group_badges(self, workspace_id: str) -> None:
        from .runner_group_widget import RunnerGroupWidget
        from .workspace_item_widget import WorkspaceItemWidget

        group = self._runner_group_items.get(workspace_id)
        if group is not None:
            header = self.list_widget.itemWidget(group, 0)
            if isinstance(header, RunnerGroupWidget):
                header.set_running_count(self._running_runner_count(workspace_id))

        # Atualiza badge de runners no workspace item (árvore flat).
        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is not None:
            widget = self.list_widget.itemWidget(ws_item, 0)
            if isinstance(widget, WorkspaceItemWidget):
                widget.set_runner_count(self._running_runner_count(workspace_id))

    def _on_runner_state_changed(
        self, workspace_id: str, runner_id: str, state: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            self._refresh_console_runners_footer()
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_state(state)
        self._update_runner_group_badges(workspace_id)
        self._refresh_console_runners_footer()

    def _on_runner_status_changed(
        self, workspace_id: str, runner_id: str, status: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            self._refresh_console_runners_footer()
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_status(status)
            item.setSizeHint(0, QSize(0, widget.preferred_height() + 2))
        self._refresh_console_runners_footer()

    def _on_runner_url_changed(
        self, workspace_id: str, runner_id: str, url: str
    ) -> None:
        from .runner_child_widget import RunnerChildWidget

        item = self._runner_tree_items.get(workspace_id, {}).get(runner_id)
        if item is None:
            self._refresh_console_runners_footer()
            return
        widget = self.list_widget.itemWidget(item, 0)
        if isinstance(widget, RunnerChildWidget):
            widget.set_url(url)
        self._refresh_console_runners_footer()

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

    def _workspace_of_item(self, item) -> "Workspace | None":
        """Sobe pelos pais até achar um Workspace. Lida com o bucket
        Sessões Claude que fica entre o terminal e o workspace."""
        node = item
        while node is not None:
            data = node.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, Workspace):
                return data
            node = node.parent()
        return None

    def _on_selection_changed(self, current, _previous) -> None:
        # Atualiza a barra branca de seleção dos consoles: zera a do
        # item anterior, liga a do novo. Só TerminalChildWidget tem
        # `set_selected`; outros widgets (workspace header, runner)
        # ignoram.
        current_data = (
            current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        )
        previous_data = (
            _previous.data(0, Qt.ItemDataRole.UserRole) if _previous is not None else None
        )
        log.info(
            "[SIDEBAR] _on_selection_changed prev=%r current=%r",
            previous_data, current_data,
        )
        for item in (_previous, current):
            if item is None:
                continue
            widget = self.list_widget.itemWidget(item, 0)
            if isinstance(widget, TerminalChildWidget):
                widget.set_selected(item is current)

        # Workspace highlight: o top-level cujo ws bate com a seleção
        # atual fica branco; os outros, cinza claro. Funciona tanto pra
        # clique direto no header do workspace quanto pra clique num
        # filho (console/runner) — `_workspace_of_item` sobe pro ws pai.
        from .workspace_item_widget import WorkspaceItemWidget
        current_ws = self._workspace_of_item(current) if current is not None else None
        current_ws_id = current_ws.id if current_ws is not None else None
        for i in range(self.list_widget.topLevelItemCount()):
            top = self.list_widget.topLevelItem(i)
            w = self.list_widget.itemWidget(top, 0)
            if isinstance(w, WorkspaceItemWidget):
                ws_at_top = self._workspace_of_item(top)
                w.set_selected(
                    ws_at_top is not None and ws_at_top.id == current_ws_id
                )

        if self.content_stack.currentIndex() != 0:
            self.content_stack.setCurrentIndex(0)
        if current is None:
            self.details.show_empty()
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)
            self._broadcast_workspace(None)
            self._update_status_bar(None)
            self._refresh_status_bar_console()
            self._refresh_console_runners_footer(None)
            return
        ws = self._workspace_of_item(current)
        log.info(
            "[SIDEBAR] _on_selection_changed → ws=%s (resolvido via _workspace_of_item)",
            ws.id if ws else None,
        )
        if ws is None:
            self._refresh_status_bar_console()
            return
        self.details.show_workspace(ws)
        self._broadcast_workspace(ws)
        self._sync_terminal_for(ws)
        self._update_status_bar(ws)
        self._refresh_status_bar_console()
        self._refresh_console_runners_footer(current)
        self.plugin_coord.dispatch_workspace_opened(ws.id)
        # Safety net: clicks em RunnerChildWidget muitas vezes não
        # disparam `itemClicked` (o widget customizado intercepta o
        # mouse). Re-dispatcha o focus a partir do selection_changed
        # — esse signal SEMPRE roda em mudança de seleção.
        if (
            isinstance(current_data, tuple)
            and len(current_data) == 3
            and current_data[0] == "runner"
        ):
            log.info(
                "[SIDEBAR] (safety net) selection_changed detectou runner — "
                "redirecionando pro _open_runner_from_sidebar"
            )
            self._open_runner_from_sidebar(ws, current_data[2])

    def _refresh_console_runners_footer(self, item=None) -> None:
        setter = getattr(self, "_set_console_runners_footer", None)
        if setter is None:
            return
        if item is None:
            item = self.list_widget.currentItem() if hasattr(self, "list_widget") else None
        if item is None:
            setter([])
            return
        ws = self._workspace_of_item(item)
        if ws is None:
            setter([])
            return
        ws = self.workspaces_coord.find_by_id(ws.id) or ws
        runners_by_id = {runner.id: runner for runner in (ws.runners or [])}
        area = self._runner_areas.get(ws.id)
        if area is not None:
            for runner in area.runners_in_scope():
                runners_by_id.setdefault(runner.id, runner)
        for area in self._console_runner_areas.get(ws.id, {}).values():
            for runner in area.runners_in_scope():
                runners_by_id.setdefault(runner.id, runner)
        runners = list(runners_by_id.values())
        if not runners:
            setter([])
            return

        def _area_for_runner(runner):
            sid = runner.console_session_id or ""
            if not sid:
                return self._runner_areas.get(ws.id)
            for area in self._console_runner_areas.get(ws.id, {}).values():
                if area.console_session_id() == sid:
                    return area
            return None

        rows: list[tuple[str, str, str, str, str, str]] = []
        for runner in runners:
            state = "idle"
            status = "parado"
            url = runner.browser_url or ""
            scope = "console" if runner.console_session_id else "workspace"
            area = _area_for_runner(runner)
            if area is not None:
                rw = area.widget_for(runner.id)
                if rw is not None:
                    state = rw.current_state()
                    status = rw.current_status_label()
                    url = rw.current_url() or url
            rows.append(
                (ws.id, runner.id, runner.name or "(runner)", state, f"{scope} · {status}", url)
            )
        setter(rows)

    def _open_footer_runner(self, workspace_id: str, runner_id: str) -> None:
        ws = self.workspaces_coord.find_by_id(workspace_id)
        if ws is None:
            return
        self._open_runner_from_sidebar(ws, runner_id)
        self._refresh_console_runners_footer()

    def _broadcast_workspace(self, workspace: Workspace | None) -> None:
        """Delega pro DockCoordinator."""
        self.dock_coord.broadcast_workspace(workspace)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        raw_data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        has_parent = item.parent() is not None if item else False
        log.info(
            "[SIDEBAR] _on_tree_item_clicked ENTRY has_parent=%s data=%r",
            has_parent, raw_data,
        )
        # Clique no header de seção (FIXADOS / WORKSPACES) → toggle.
        if raw_data == self._SECTION_HEADER_ROLE:
            label = item.data(0, self._SECTION_LABEL_ROLE)
            if isinstance(label, str):
                self._toggle_section_collapsed(label)
            return
        # Clique no workspace (top-level) → toggle expand/collapse + navega ao terminal.
        if item.parent() is None and isinstance(raw_data, Workspace):
            new_expanded = not item.isExpanded()
            item.setExpanded(new_expanded)
            from .workspace_item_widget import WorkspaceItemWidget
            w = self.list_widget.itemWidget(item, 0)
            if isinstance(w, WorkspaceItemWidget):
                w.set_collapsed(not new_expanded)
            self.settings.workspace_collapsed[raw_data.id] = not new_expanded
            try:
                self.settings.save()
            except OSError:
                pass
            self._ensure_terminal_pane_visible()
            self._last_synced_ws_id = None
            self._sync_terminal_for(raw_data)
            self._update_status_bar(raw_data)
            return
        # Clique simples numa aba ativa/em ação (tab_id) já foca a aba.
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        # Runner click é tratado em `_on_selection_changed` (safety net).
        # Não duplicar aqui — evita 2x `_open_runner_from_sidebar`
        # (com `_focus_pane_from_sidebar` chamado 2x), que era a causa
        # da lentidão visível em cada click.
        if isinstance(data, tuple) and len(data) == 3 and data[0] == "runner":
            return
        if not isinstance(data, int):  # só tab_id de aba viva
            return
        # Sobe pelos pais até achar o workspace (terminal agora vive
        # dentro do bucket Sessões Claude, que fica entre).
        ws = self._workspace_of_item(item)
        if ws is None:
            return
        self._focus_terminal_tab(ws, data)

    def _on_tree_item_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        # Double-click ou Enter numa aba viva foca a aba existente.
        if item.parent() is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        ws = self._workspace_of_item(item)
        if ws is None:
            return
        # Linha de runner ("footer") → abre aba Runners + foca o runner
        if (
            isinstance(data, tuple)
            and len(data) == 3
            and data[0] == "runner"
        ):
            self._open_runner_from_sidebar(ws, data[2])
            return
        if not isinstance(data, int):  # tab_id
            return
        self._focus_terminal_tab(ws, data)

    def _animate_bottom_sub_splitter(self, target: list[int]) -> None:
        """Anima `_bottom_sub_splitter.setSizes` ao longo de ~180ms.

        Por que: trocar de [617, 308] pra [0, 907] num único frame
        deixa o user com a sensação de "click ficou travado" — o
        QWebEngineView dos panes (console xterm + runner xterm) leva
        ~100-200ms pra repintar no novo tamanho, e como o tamanho
        final é aplicado de uma vez, todo esse delay aparece após o
        click. Animando, o tamanho cresce/diminui em frames intermediários
        — o user vê movimento imediato e a percepção de lag some.
        """
        from PySide6.QtCore import QEasingCurve, QVariantAnimation

        # Cancela animação anterior (se houver) — evita queue de
        # animações conflitantes ao clicar rápido entre runner/console.
        old = getattr(self, "_sub_splitter_anim", None)
        if old is not None and old.state() == old.State.Running:
            old.stop()

        start = list(self._bottom_sub_splitter.sizes())
        # Se start e target não baterem em tamanho, aplica direto sem anim.
        if len(start) != len(target) or not start:
            self._bottom_sub_splitter.setSizes(target)
            return
        # Normaliza pro mesmo total — splitter mantém soma fixa.
        total = sum(start) or sum(target) or 1
        if sum(target) != total and sum(target) > 0:
            scale = total / sum(target)
            target = [int(v * scale) for v in target]

        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _tick(t: float, s=start, e=target) -> None:
            vals = [int(s[i] + (e[i] - s[i]) * t) for i in range(len(s))]
            self._bottom_sub_splitter.setSizes(vals)

        anim.valueChanged.connect(_tick)
        self._sub_splitter_anim = anim
        anim.start()

    def _focus_pane_from_sidebar(self, pane: str) -> None:
        """Click pelo sidebar = "focar" o pane escolhido dentro do
        `_bottom_sub_splitter`. `pane` ∈ {"runners", "runners_console",
        "terminal"}.

        Mantém o workspace upper como estiver (não auto-minimiza —
        causava lentidão visível em cada click). Atualiza chips/ícones
        inline pra refletir quem está colapsado."""
        if not hasattr(self, "_bottom_sub_splitter"):
            log.info("[FOCUS] _bottom_sub_splitter ainda não existe, abort")
            return
        import time
        _fp_t0 = time.perf_counter()
        from PySide6.QtCore import QSize as _QS

        from .icons import ic

        cache = getattr(self, "_focus_icon_cache", None)
        if cache is None:
            cache = {
                "min": ic("fa5s.window-minimize", color="#c8c8c8"),
                "max": ic("fa5s.window-maximize", color="#c8c8c8"),
            }
            self._focus_icon_cache = cache
        icon_min = cache["min"]
        icon_max = cache["max"]

        self._terminal_pane_widget.setMinimumHeight(0)
        self._runners_pane.setMinimumHeight(0)
        self._runners_console_pane.setMinimumHeight(0)
        # Toggles individuais escondem via setVisible(False); precisamos
        # garantir que estão visíveis antes de redimensionar.
        self._terminal_pane_widget.setVisible(True)
        self._runners_pane.setVisible(True)
        self._runners_console_pane.setVisible(False)

        cur = self._bottom_sub_splitter.sizes()
        total = sum(cur)
        h = self._bottom_sub_splitter.height()
        if h > total:
            total = h
        if total < 200:
            total = 600
        # Garante len 3 — caso saved sizes ainda não tenham sido aplicados.
        if len(cur) != 3:
            cur = [total // 2, total // 2, 0]

        # Salva last_size do pane focado antes de zerar — restauração
        # posterior precisa de um valor sensato.
        if pane == "terminal":
            if cur[1] > 4:
                self._runners_last_size = cur[1]
            target = [total, 0, 0]
            chips_add = [("runners", "Runners", "mdi6.source-branch")]
            chips_remove = ["terminal_pane"]
            btns_to_max = [self._runners_minimize_btn]
            btns_to_min = [self._terminal_pane_minimize_btn]
        elif pane == "runners":
            if cur[0] > 4:
                self._terminal_pane_last_size = cur[0]
            runner_target = getattr(self, "_runners_last_size", 320) or 320
            runner_target = min(max(runner_target, 240), max(total // 2, 240))
            runner_target = min(runner_target, max(total - 220, 120))
            target = [max(total - runner_target, 220), runner_target, 0]
            chips_add = []
            chips_remove = ["terminal_pane", "runners"]
            btns_to_max = []
            btns_to_min = [self._terminal_pane_minimize_btn, self._runners_minimize_btn]
        elif pane == "runners_console":
            return
        else:
            return

        self._animate_bottom_sub_splitter(target)
        if hasattr(self, "_minimize_tray"):
            for cid in chips_remove:
                self._minimize_tray.remove_chip(cid)
            self._minimize_tray.remove_chip("runners_console")
            for cid, lbl, ico in chips_add:
                self._minimize_tray.add_chip(cid, lbl, ico)
        for b in btns_to_min:
            b.setIcon(icon_min)
            b.setIconSize(_QS(11, 11))
        for b in btns_to_max:
            b.setIcon(icon_max)
            b.setIconSize(_QS(11, 11))

        log.info(
            "[FOCUS-PERF] _focus_pane_from_sidebar(%s) dt=%.1fms",
            pane, (time.perf_counter() - _fp_t0) * 1000,
        )
        self._schedule_layout_save()

    def _ensure_runners_pane_visible(self) -> None:
        self._focus_pane_from_sidebar("runners")

    def _ensure_runners_console_pane_visible(self) -> None:
        self._focus_pane_from_sidebar("runners_console")

    def _ensure_terminal_pane_visible(self) -> None:
        self._focus_pane_from_sidebar("terminal")

    def _open_runner_from_sidebar(self, workspace: Workspace, runner_id: str) -> None:
        """Switch pro bottom tab "Runners" e foca a aba do runner.

        Resolve o escopo automaticamente: runners workspace-scope abrem
        no painel "Runners workspace"; runners de console abrem no painel
        "Runners (console)" do console dono."""
        import time
        t0 = time.perf_counter()
        log.info(
            "[SIDEBAR] _open_runner_from_sidebar ws=%s runner=%s",
            workspace.id, runner_id,
        )
        self._open_runner_t0 = t0
        # Identifica o escopo procurando o runner no workspace.
        runner = next((r for r in workspace.runners if r.id == runner_id), None)
        sid = (runner.console_session_id or "") if runner is not None else ""
        log.info(
            "[SIDEBAR] runner encontrado=%s sid=%r",
            runner is not None, sid,
        )
        if sid:
            # Console-scope: foca o pane "Runners console" + localiza area.
            self._ensure_runners_console_pane_visible()
            for area in self._console_runner_areas.get(workspace.id, {}).values():
                if area.console_session_id() == sid:
                    self.console_runner_host.setCurrentWidget(area)
                    area.focus_runner(runner_id)
                    return
            # Área ainda não criada → garante criando via terminal dono.
            for tab_id, _term_item in self.terminals_coord.state.tree_items.items():
                term = self._terminal_widget_for(tab_id)
                if term is None:
                    continue
                term_sid = term.claimed_session_id() or self._pending_console_key(term)
                if term_sid == sid:
                    area = self._ensure_terminal_runner_panel(workspace, term)
                    area.focus_runner(runner_id)
                    return
            # Não achou console dono (foi encerrado?) — fallback pro workspace.
        # Workspace-scope: foca o pane "Runners" (workspace).
        self._ensure_runners_pane_visible()
        log.info("[SIDEBAR] usando workspace-scope runner area (fallback)")
        import time
        t1 = time.perf_counter()
        area = self._get_or_create_runner_area(workspace)
        t2 = time.perf_counter()
        self.runner_host.setCurrentWidget(area)
        t3 = time.perf_counter()
        t4 = time.perf_counter()
        area.focus_runner(runner_id)
        t5 = time.perf_counter()
        total = (t5 - getattr(self, "_open_runner_t0", t1)) * 1000
        log.info(
            "[SIDEBAR-PERF] _open_runner_from_sidebar dt_total=%.1fms "
            "get_area=%.1fms runner_host_set=%.1fms tabs_set=%.1fms "
            "focus_runner=%.1fms",
            total,
            (t2 - t1) * 1000,
            (t3 - t2) * 1000,
            (t4 - t3) * 1000,
            (t5 - t4) * 1000,
        )

    def _focus_terminal_tab(self, workspace: Workspace, tab_id: int) -> None:
        import time
        ft_t0 = time.perf_counter()
        log.info(
            "[SIDEBAR] _focus_terminal_tab ws=%s tab_id=%s",
            workspace.id, tab_id,
        )
        # Antes de focar: se o terminal pane está minimizado, restaura e
        # minimiza o runners pane no mesmo gesto.
        self._ensure_terminal_pane_visible()
        area = self.terminals_coord._areas.get(workspace.id)
        if area is None:
            log.info("[SIDEBAR] sem TerminalArea pra workspace=%s", workspace.id)
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                self._bottom_tabs.setCurrentWidget(self.terminal_host)
                self._refresh_terminal_pane_title()
                log.info(
                    "[SIDEBAR-PERF] _focus_terminal_tab dt=%.1fms",
                    (time.perf_counter() - ft_t0) * 1000,
                )
                break

    def _show_settings(self) -> None:
        # Garante que estamos na view de workspaces (settings vive no
        # content_stack interno do body_splitter)
        self.main_stack.setCurrentWidget(self.body_view)
        # Se o painel central estiver minimizado, restaura antes de exibir
        # as settings — caso contrário a tela aparece em área 0×0.
        if hasattr(self, "_bottom_sub_splitter") and self._terminal_pane_is_minimized():
            self._toggle_terminal_pane_minimized()
        # Se o content_stack estiver oculto (workspace minimizado), mostra
        # antes de exibir settings — sem isso a tela não aparece.
        if not self.content_stack.isVisible():
            self._toggle_content_minimized()
        self.activity_bar.set_active(VIEW_SETTINGS)
        self.content_stack.setCurrentWidget(self._settings_scroll)

    def _show_workspaces(self) -> None:
        self.main_stack.setCurrentWidget(self.body_view)
        self.activity_bar.set_active(VIEW_WORKSPACES)
        self.content_stack.setCurrentIndex(0)
        current = self.list_widget.currentItem()
        if current:
            ws = current.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(ws, Workspace):
                self.details.show_workspace(ws)
                self._sync_terminal_for(ws)

    # ---------- terminal ----------

    def _sync_terminal_for(self, workspace: Workspace) -> None:
        # Curtocircuita se já estamos exibindo este workspace — clicks
        # entre filhos do mesmo ws (consoles, runners) não precisam
        # re-rodar `_get_or_create_runner_area` nem
        # `_refresh_runner_children` (caros e responsáveis pela
        # lentidão visível em cada click do sidebar).
        last_id = getattr(self, "_last_synced_ws_id", None)
        if last_id == workspace.id:
            return
        self._last_synced_ws_id = workspace.id
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
        # Views contextuais (MCP, Catalog, Hooks) atualizam ao trocar workspace
        # mesmo se já estiverem visíveis — evita mostrar dados do ws anterior.
        if hasattr(self, "mcp_view") and self.main_stack.currentWidget() is self.mcp_view:
            self.mcp_view.set_workspace(workspace)
        if hasattr(self, "catalog_view") and self.main_stack.currentWidget() is self.catalog_view:
            self.catalog_view.set_workspace(workspace)
        if hasattr(self, "hooks_view") and self.main_stack.currentWidget() is self.hooks_view:
            self.hooks_view.set_workspace(workspace)

    def _refresh_terminal_pane_title(self) -> None:
        """Atualiza o header do terminal pane com workspace + console
        atualmente selecionados, em destaque. Substitui a tab bar interna
        do TerminalArea (que foi escondida) como única fonte do "qual
        console estou olhando"."""
        if not hasattr(self, "_terminal_pane_title"):
            return
        area = self._active_terminal_area()
        term = area.tabs.currentWidget() if area is not None else None
        # Workspace: resolve a partir da própria area ativa — não usa
        # `_current_workspace()` porque o item selecionado no sidebar
        # pode ser um console/runner (filhos do bucket) e o helper
        # antigo só subia 1 nível, dando None nesses casos.
        ws = None
        if area is not None:
            for ws_id, a in self.terminals_coord._areas.items():
                if a is area:
                    ws = self.workspaces_coord.find_by_id(ws_id)
                    break
        if ws is None or term is None or not isinstance(term, TerminalWidget):
            placeholder = (
                "<span style='color:#666'>Claude console — "
                "selecione um console no sidebar</span>"
            )
            if getattr(self, "_terminal_pane_title_last", None) != placeholder:
                log.info("[HEADER] → placeholder (ws/area/term faltando)")
                self._terminal_pane_title.setText(placeholder)
                self._terminal_pane_title_last = placeholder
            return
        # `#N título` no mesmo formato usado pelo sidebar/área.
        try:
            display = area._compute_tab_display(term)
        except Exception:
            display = term.effective_title() or "console"
        # Trunca o título do console pra evitar que empurre o sizeHint do
        # label e force scroll horizontal na janela.
        if len(display) > 48:
            display = display[:47] + "…"
        ws_html = (
            f"<span style='color:#5ac35a;font-weight:600'>{ws.name}</span>"
        )
        console_html = (
            f"<span style='color:#e5b53b;font-weight:600'>{display}</span>"
        )
        # Branch + model: lookup do TerminalChildWidget correspondente
        # (mesma fonte usada pelo footer / status bar) — não duplicar
        # lógica de extrair branch do git/model do JSONL.
        branch_html = ""
        model_html = ""
        try:
            tab_id = id(term)
            tree_item = self.terminals_coord.state.tree_items.get(tab_id)
            if tree_item is not None:
                child = self.list_widget.itemWidget(tree_item, 0)
                if isinstance(child, TerminalChildWidget):
                    info = child.status_info()
                    branch = (info.get("branch") or "").strip()
                    modified = int(info.get("modified") or 0)
                    model = (info.get("model") or "").strip()
                    if branch:
                        short = branch if len(branch) <= 35 else branch[:34] + "…"
                        mod_html = (
                            f" <span style='color:#ff9d3b'>●{modified}</span>"
                            if modified > 0 else ""
                        )
                        branch_html = (
                            f" <span style='color:#555'>·</span> "
                            f"<span style='color:#9aa0a6'>branch</span> "
                            f"<span style='color:#e5b53b;font-weight:600'>"
                            f"⎇ {short}</span>{mod_html}"
                        )
                    if model:
                        model_html = (
                            f" <span style='color:#555'>·</span> "
                            f"<span style='color:#9aa0a6'>modelo</span> "
                            f"<span style='color:#6aa9e0;font-weight:600'>"
                            f"{model}</span>"
                        )
        except Exception:
            pass
        # MCPs do workspace (scope=project) — exclui MCPs globais do user
        # (~/.claude.json) que são comuns a todos os workspaces e poluem.
        mcp_html = ""
        try:
            from ..services.mcp_inspector import SCOPE_PROJECT, list_servers
            mcp_names = sorted({
                s.name for s in list_servers(list(ws.folders))
                if s.scope == SCOPE_PROJECT
            })
        except Exception:
            mcp_names = []
        if mcp_names:
            shown = ", ".join(mcp_names[:4])
            if len(mcp_names) > 4:
                shown += f" +{len(mcp_names) - 4}"
            mcp_html = (
                f" <span style='color:#555'>·</span> "
                f"<span style='color:#9aa0a6'>mcp</span> "
                f"<span style='color:#6cc7ce;font-weight:600'>🔌 {shown}</span>"
            )
        # Linha 1: workspace · console
        # Linha 2: branch · modelo · mcp  (só se houver algum desses campos)
        line1 = (
            f"<span style='color:#9aa0a6'>workspace</span> {ws_html} "
            f"<span style='color:#555'>·</span> "
            f"<span style='color:#9aa0a6'>console</span> {console_html}"
        )
        # Cada frag começa com " <span...>·</span> conteúdo" — extrai só
        # o conteúdo removendo o prefixo " · " HTML pra montar a linha 2
        # sem separador inicial desnecessário.
        _DOT_PREFIX = " <span style='color:#555'>·</span> "
        line2_parts: list[str] = [
            frag[len(_DOT_PREFIX):] if frag.startswith(_DOT_PREFIX) else frag
            for frag in (branch_html, model_html, mcp_html)
            if frag
        ]
        line2 = _DOT_PREFIX.join(line2_parts)
        new_text = line1 + ("<br>" + line2 if line2 else "")
        # Curtocircuita: setText em QLabel rich-text força relayout e
        # re-render. Sem essa cache, sinais frequentes (currentChanged
        # encadeados via `_sync_terminal_for`) ficam chamando setText
        # com mesmo texto.
        if getattr(self, "_terminal_pane_title_last", None) == new_text:
            return
        self._terminal_pane_title.setText(new_text)
        self._terminal_pane_title.setToolTip(
            "MCPs ativos:\n• " + "\n• ".join(mcp_names) if mcp_names else ""
        )
        self._terminal_pane_title_last = new_text

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
        area.runners_changed.connect(self._refresh_console_runners_footer)
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

    def _run_all_workspace_runners(self, workspace: Workspace) -> None:
        # Garante a RunnerArea (cobre clique no ▶ sem ter aberto o pane).
        area = self._get_or_create_runner_area(workspace)
        area.run_all()

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

    def _run_all_console_runners(self, workspace: Workspace, terminal) -> None:
        area = self._ensure_terminal_runner_panel(workspace, terminal)
        area.run_all()

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
            on_edit_with_claude=lambda cfg, w=workspace, csid=console_session_id:
                self._edit_runner_with_claude(w, cfg, csid),
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
            # Já existe — só foca o pane "Runners console" e seleciona a area.
            self.console_runner_host.setCurrentWidget(existing)
            self._ensure_runners_console_pane_visible()
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
        area.runners_changed.connect(self._refresh_console_runners_footer)
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
        # Painel mora no pane "Runners console" (separado) — não embute mais
        # no próprio terminal. O toolbar `▤ Runners` do terminal foca o pane.
        self.console_runner_host.addWidget(area)
        self.console_runner_host.setCurrentWidget(area)
        self._ensure_runners_console_pane_visible()
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
                "Não foi possível abrir a IA",
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

        backend = self.settings.ai_backend
        if mode == "resume":
            entry = dlg.selected_entry()
            if entry is None:
                return
            if backend == "opencode":
                argv = [
                    self.settings.ai_command(),
                    *self.settings.ai_launch_args(),
                    "-s", entry.session_id,
                    entry.cwd,
                ]
            else:
                argv = [
                    self.settings.claude_command,
                    *self.settings.claude_launch_args(),
                    "--resume",
                    entry.session_id,
                ]
                argv += ["--add-dir", str(repo)]
                for extra in extras:
                    argv += ["--add-dir", extra]
            title = f"runner-gen #{area.count() + 1} (resume)"
            terminal = area.add_terminal(title)
            terminal.configure_claude(entry.cwd, resume_id=entry.session_id, backend=backend)
            label = f"{backend} (runner-gen resume) — {workspace.name}"
            cwd = entry.cwd
        else:
            hint = dlg.hint()
            spec_path = Path(repo) / "docs" / "runners-spec.md"
            prompt = build_generate_prompt(workspace, hint, spec_path=spec_path)
            if backend == "opencode":
                argv = [
                    self.settings.ai_command(),
                    *self.settings.ai_launch_args(),
                    "--prompt", prompt,
                    ws_cwd,
                ]
            else:
                argv = [
                    self.settings.claude_command,
                    *self.settings.claude_launch_args(),
                    prompt,
                ]
            title = f"runner-gen #{area.count() + 1}"
            terminal = area.add_terminal(title)
            terminal.configure_claude(ws_cwd, backend=backend)
            label = f"{backend} (runner-gen) — {workspace.name}"
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
            QMessageBox.warning(self, "Não foi possível abrir a IA", str(e))
            ws = self._current_workspace()
            self.emit_workspace_error(
                "Falha ao abrir a IA",
                workspace_id=ws.id if ws else None,
                body=str(e),
                critical=True,
            )
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

    def _recent_runner_output(self, workspace, runner_id: str) -> str:
        """Saída recente do runner `runner_id` em qualquer área que o mostre
        (painel do workspace ou painéis de console)."""
        area = self._runner_areas.get(workspace.id)
        if area is not None:
            out = area.recent_output_for(runner_id)
            if out:
                return out
        for area in self._console_runner_areas.get(workspace.id, {}).values():
            out = area.recent_output_for(runner_id)
            if out:
                return out
        return ""

    def _edit_runner_with_claude(self, workspace, runner, console_session_id="") -> None:
        from ..launchers import find_app_repo_root
        from ..services.runner_gen_history import RunnerGenEntry, add_entry
        from ..services.runner_prompt import build_edit_prompt

        repo = find_app_repo_root()
        if repo is None:
            QMessageBox.warning(
                self,
                "Não foi possível abrir a IA",
                "Repositório do claude-workspaces não encontrado — o editor "
                "precisa rodar no diretório do projeto pra ler docs/runners-spec.md",
            )
            return
        if not workspace.folders:
            QMessageBox.warning(
                self,
                "Workspace sem pastas",
                "Adicione ao menos uma pasta no workspace antes de editar runner.",
            )
            return

        hint, ok = QInputDialog.getText(
            self,
            "Editar com IA",
            f"O que você quer ajustar no runner '{runner.name}'?\n"
            "(opcional — o erro/saída recente já vai junto)",
        )
        if not ok:
            return

        recent = self._recent_runner_output(workspace, runner.id)
        spec_path = Path(repo) / "docs" / "runners-spec.md"
        prompt = build_edit_prompt(
            workspace, runner, hint=hint, recent_output=recent, spec_path=spec_path
        )

        area = self.terminals_coord.get_or_create_area(workspace)
        ws_cwd, _extras = workspace.launch_paths()
        # cwd do Claude: a pasta do runner quando definida (melhor contexto pro
        # diagnóstico), senão o cwd padrão do workspace.
        cwd = (runner.cwd or "").strip() or ws_cwd
        backend = self.settings.ai_backend
        if backend == "opencode":
            argv = [
                self.settings.ai_command(),
                *self.settings.ai_launch_args(),
                "--prompt", prompt,
                cwd,
            ]
        else:
            argv = [
                self.settings.claude_command,
                *self.settings.claude_launch_args(),
                prompt,
            ]
        title = f"runner-edit #{area.count() + 1}"
        terminal = area.add_terminal(title)
        terminal.configure_claude(cwd, backend=backend)
        label = f"{backend} (runner-edit) — {workspace.name}"

        ws_id = workspace.id

        def _record_once(sid: str, *, _t=terminal, _cwd=cwd, _ws=ws_id, _hint=hint) -> None:
            if not sid:
                return
            try:
                add_entry(RunnerGenEntry(
                    workspace_id=_ws, session_id=sid, cwd=_cwd, hint=_hint,
                ))
            except Exception:
                log.exception("Falha ao registrar runner-edit no histórico")
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
            QMessageBox.warning(self, "Não foi possível abrir a IA", str(e))
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)
        from .persistent_toast import flash_toast
        flash_toast(
            "Agente aberto pra editar o runner. Quando ele salvar o rascunho, "
            "clique em 'Recarregar' na aba de runners pra aplicar."
        )

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
        backend = self.settings.ai_backend
        if backend == "opencode":
            repo = find_app_repo_root()
            argv = [
                self.settings.ai_command(),
                *self.settings.ai_launch_args(),
                "-s", session_id,
                cwd,
            ]
        else:
            from ..claude_sessions import project_sessions_dir
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
                *self.settings.claude_launch_args(),
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
        terminal.configure_claude(cwd, resume_id=session_id, backend=backend)
        label = f"{backend} (runner-gen resume) — {workspace.name}"
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
        self._refresh_console_runners_footer()

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
        # Header do terminal pane mostra workspace+console+branch+model.
        # Atualiza em:
        #   - currentChanged (troca de console)
        #   - tab_activity_changed (rename/status — também usado pra
        #     re-render branch/model porque o status_info do
        #     TerminalChildWidget é atualizado lá)
        # `_refresh_terminal_pane_title` cacheia `_terminal_pane_title_last`
        # e curtocircuita se o texto não muda — então signals de
        # atividade pura (sem mudança de title/branch/model) viram
        # no-op, sem cost de HTML render.
        area.tabs.currentChanged.connect(
            lambda _i: self._refresh_terminal_pane_title()
        )
        area.tab_activity_changed.connect(
            lambda *_a: self._refresh_terminal_pane_title()
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

        # Long-running tracking: marca quando entrou em working, limpa
        # quando sai. _scan_long_running emite a notif depois do threshold.
        if is_working:
            if tab_id not in self._working_since:
                import time as _t
                self._working_since[tab_id] = _t.monotonic()
        else:
            self._working_since.pop(tab_id, None)
            self._long_running_notified.discard(tab_id)

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
        # Aba que saiu pode ter sido a única causa de colisão — re-disambigua.
        # parent_item agora é o bucket Sessões Claude (não o workspace);
        # _refresh_workspace_child_titles tolera, e _refresh_empty_placeholder
        # precisa receber o workspace real → sobe um nível se for bucket.
        if parent_item is not None:
            self._refresh_workspace_child_titles(parent_item)
            ws_real = parent_item
            if parent_item.data(0, Qt.ItemDataRole.UserRole) == self._SESSOES_BUCKET_ROLE:
                ws_real = parent_item.parent() or parent_item
                # Atualiza badge de contagem do bucket
                self._refresh_sessoes_count(ws_real)
            # Se o workspace ficou sem nenhum console, restaura o placeholder
            # com botão "Nova sessão do claude…" pra dar uma ação visível.
            self._refresh_empty_placeholder(ws_real)
            # Auto-collapse: após tudo resetado, colapsa se não restam consoles.
            if ws_real.isExpanded() and not list(self._iter_terminal_items(ws_real)):
                ws_real.setExpanded(False)
                self._update_workspace_collapsed_icon(ws_real, collapsed=True)
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
        # Footer reflete o console selecionado — re-renderiza a cada
        # segundo pra atualizar cronômetro de ocioso e captar trocas
        # de estado/branch sem precisar engatar callback em cada update.
        self._refresh_status_bar_console()

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
        # TrayNotifier sincroniza tooltip + menu com o NotificationService.
        # Criado depois do service (no __init__) e depois do tray; idempotente.
        try:
            from ..notifications.tray import TrayNotifier
            self._tray_notifier = TrayNotifier(
                self.notif_service,
                self._tray,
                app_name=self.settings.notify_app_name or "Claude Workspaces",
                parent=self,
            )
            self._tray_notifier.open_target_requested.connect(
                self._on_notif_open_target
            )
            self._tray_notifier.show_window_requested.connect(self._show_and_focus)
            from PySide6.QtWidgets import QApplication
            self._tray_notifier.quit_requested.connect(QApplication.quit)
        except Exception:
            log.exception("falha ao inicializar TrayNotifier")

    def _show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

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
        if notifier.available:
            self._desktop_notifier = notifier
            # Escuta ações disparadas em QUALQUER notificação D-Bus (inclusive
            # as emitidas pelo notify-hook.py rodando em subprocess do Claude
            # Code). Filtramos por prefixo `open-console:` pra não colidir
            # com as actions internas do inbox alert ("open"/"snooze5"/"seen").
            notifier.action_invoked.connect(self._on_global_dbus_action)
            log.info("Notificador D-Bus com ações ativo (caps=%s)", notifier.capabilities)
            # DesktopNotifierAdapter: escuta NotificationService e despacha
            # popup automático respeitando preferências (mute, app em foco).
            try:
                from ..notifications.desktop import DesktopNotifierAdapter
                self._desktop_adapter = DesktopNotifierAdapter(
                    self.notif_service,
                    notifier,
                    is_app_focused=self._is_app_in_foreground,
                    timeout_ms_provider=lambda: self.settings.notify_timeout_ms,
                    is_target_visible=self._is_notification_target_visible,
                    fallback_notify=self._show_tray_message,
                    parent=self,
                )
                self._desktop_adapter.open_target_requested.connect(
                    self._on_notif_open_target
                )
            except Exception:
                log.exception("falha ao montar DesktopNotifierAdapter")
        else:
            self._desktop_notifier = None
            log.info(
                "Notificador D-Bus indisponível (available=%s actions=%s) — "
                "caindo pro tray.showMessage",
                notifier.available, notifier.supports_actions,
            )

    def _show_tray_message(self, title: str, body: str) -> None:
        if not self.settings.notify_native_enabled or self._tray is None:
            return
        try:
            self._tray.showMessage(
                title,
                body,
                QSystemTrayIcon.MessageIcon.Information,
                max(3000, int(self.settings.notify_timeout_ms or 6000)),
            )
        except Exception:
            log.debug("showMessage falhou", exc_info=True)

    def _is_app_in_foreground(self) -> bool:
        """True se a MainWindow está ativa e visível."""
        try:
            return self.isActiveWindow() and not self.isMinimized() and self.isVisible()
        except Exception:
            return False

    def _is_notification_target_visible(self, n) -> bool:
        """True só se o tab/console alvo da notificação é EXATAMENTE o que o
        usuário está vendo agora. Usado pelo DesktopNotifierAdapter pra
        decidir se suprime o popup nativo. Sem `tab_id` (notif genérica),
        cai pro critério clássico de "app em foco" — não dá pra afirmar que
        o usuário "já viu" sem saber de qual console é o alerta.
        """
        if not self._is_app_in_foreground():
            return False
        tab_id = getattr(n, "tab_id", None)
        if tab_id is None:
            # Sem alvo específico: se o app inteiro está focado, assume visto.
            return True
        if self.terminal_host is None:
            return False
        try:
            area = self.terminal_host.currentWidget()
            tabs = getattr(area, "tabs", None) if area is not None else None
            current = tabs.currentWidget() if tabs is not None else None
            return current is not None and id(current) == int(tab_id)
        except Exception:
            return False

    def _on_inbox_alert(
        self, tab_id: int, info: dict, is_reminder: bool
    ) -> None:
        """Recebe alerta primário (working→idle) ou re-lembrete (timer).
        Tenta D-Bus com botões; cai pro tray.showMessage se indisponível."""
        if not self.settings.notify_native_enabled:
            return
        # Se o usuário já tá olhando pra esse console (janela ativa + área
        # do workspace selecionada + aba específica do console visível),
        # não notifica — ele acabou de ver o "Pronto" na própria tela.
        # `terminal_host.currentWidget()` é a `TerminalArea` do workspace
        # ativo; o `TerminalChildWidget` (cujo `id()` é o tab_id) fica em
        # `area.tabs.currentWidget()`. Reminders também ficam silenciados
        # nesse caso, senão o timer fica disparando popup sobre uma janela
        # já focada. Outras janelas, outro tab ou app no tray continuam
        # alertando normal.
        if (
            self.isActiveWindow()
            and not self.isMinimized()
            and self.terminal_host is not None
        ):
            area = self.terminal_host.currentWidget()
            tabs = getattr(area, "tabs", None) if area is not None else None
            current = tabs.currentWidget() if tabs is not None else None
            if current is not None and id(current) == tab_id:
                log.debug(
                    "inbox_alert suprimido — console %s já está visível e em foco",
                    tab_id,
                )
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
        # Body: só o título da sessão (custom name ou preview do primeiro
        # prompt). O `status` parsed do TUI traz lixo tipo o footer de
        # "Context/Usage/Weekly", que polui o popup e não ajuda em nada —
        # quem quer detalhe abre o app. Status só entra como fallback se
        # o título estiver vazio.
        title_text = str(info.get("title") or "").strip()
        if title_text:
            body = title_text
        else:
            status = str(info.get("status") or "").strip()
            if len(status) > 90:
                status = status[:89] + "…"
            body = status or "Console pronto pra próxima instrução."
        self._last_alert_tab_id = tab_id
        workspace_id = info.get("workspace_id", "")

        # ----- Espelha pro NotificationService (fonte de verdade do sino
        # e do NotificationCenter). Type=agent_waiting porque "console
        # working→idle" é exatamente "agente aguardando próxima instrução".
        # Cooldown/dedup do service evita spam, e suprimimos quando o
        # console já está em foco (mesmo critério acima).
        notif_kind = (
            NotificationKind.PERMISSION_REQUIRED
            if str(info.get("kind", "")) == "decision"
            else NotificationKind.AGENT_WAITING
        )
        session_id = str(info.get("session_id") or "")
        self.notif_service.notify(
            notif_kind,
            title=title,
            body=body,
            workspace_id=workspace_id or None,
            session_id=session_id or None,
            tab_id=tab_id,
            data={
                "source": "inbox_alert",
                "is_reminder": bool(is_reminder),
            },
        )
        # Toast in-app top-most: continua só pro som (a função foi reduzida
        # antes a "só toca som"; mantemos por enquanto).
        self._show_persistent_toast(tab_id, workspace_id, title, body)

        # Despacho do popup D-Bus agora é responsabilidade do
        # DesktopNotifierAdapter (escuta notification_added do service e
        # respeita "app em foco", muted_kinds, etc.). O `notify()` acima já
        # disparou notification_added — adapter cuida do resto.
        if self._desktop_notifier is not None:
            return

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
        """Toast in-app quando o app está em foco e o popup nativo pode não aparecer."""
        sound_name = (
            self.settings.notify_sound_name.strip()
            if self.settings.notify_sound_enabled else ""
        )
        if sound_name:
            from ..services.desktop_notifier import _play_sound_async
            _play_sound_async(sound_name)
        # Toast visual — só quando em foco (app em background: popup nativo cobre).
        if not self._is_app_in_foreground():
            return
        existing = self._active_toasts.get(tab_id)
        if existing is not None and not existing.isHidden():
            existing.update_content(title, body)
            return
        toast = PersistentToast(title, body, duration_ms=8000)
        toast.action_clicked.connect(lambda: self._handle_toast_action(tab_id, workspace_id))
        toast.dismissed.connect(lambda: self._on_toast_dismissed(tab_id))
        toast.snoozed.connect(lambda: self._on_toast_dismissed(tab_id))
        toast.seen.connect(lambda: self._on_toast_dismissed(tab_id))
        self._active_toasts[tab_id] = toast
        position_toasts(list(self._active_toasts.values()))
        toast.show()

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
        # Marca a notif "agent_waiting" correspondente como vista no service
        # (não dismiss — usuário pode querer ver o histórico). Busca pela
        # tab_id; pode haver mais de uma se o mesmo console gerou perm+waiting,
        # então iteramos.
        for n in self.notif_service.list(only_unseen=True):
            if n.tab_id == tab_id and n.kind in (
                NotificationKind.AGENT_WAITING,
                NotificationKind.PERMISSION_REQUIRED,
            ):
                self.notif_service.mark_seen(n.id)
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
        """Abre o NotificationCenter (popup) embaixo da bell."""
        if self._notif_center is None:
            self._notif_center = NotificationCenter(
                self.notif_service,
                workspace_name_fn=self._workspace_name_for_notif,
                parent=self,
            )
            self._notif_center.open_target_requested.connect(
                self._on_notif_open_target
            )
        self._notif_center.show_at(self.top_bar._inbox_btn)

    def _workspace_name_for_notif(self, workspace_id: str) -> str:
        ws = self.workspaces_coord.find_by_id(workspace_id)
        return ws.name if ws else workspace_id

    def _on_notif_open_target(self, notification) -> None:
        """Click em 'Abrir' num card do NotificationCenter."""
        ws_id = notification.workspace_id
        tab_id = notification.tab_id
        if ws_id and tab_id is not None:
            self._focus_tab_from_inbox(ws_id, int(tab_id))
            return
        sid = notification.session_id
        if sid and self._focus_terminal_by_session_id(sid):
            return
        if ws_id:
            ws_item = self._find_workspace_item(ws_id)
            if ws_item is not None:
                self.list_widget.setCurrentItem(ws_item)

    def _on_notif_reminder_due(self, notification) -> None:
        """Service mandou relembrar uma pendência. Entrega real (desktop /
        tray) é despachada no `_on_inbox_alert` quando o terminals_coord
        relembra; aqui só log pra debug."""
        log.debug(
            "reminder_due: id=%s kind=%s ws=%s",
            notification.id, notification.kind, notification.workspace_id,
        )

    def _focus_tab_from_inbox(self, workspace_id: str, tab_id: int) -> None:
        self.terminals_coord.remove_from_inbox(tab_id)
        ws_item = self._find_workspace_item(workspace_id)
        # Marca o console específico no sidebar (não só o workspace) —
        # ao clicar "Abrir console" na notif, o usuário espera ver o
        # row do console destacado, não só o workspace selecionado.
        if ws_item is not None:
            # Árvore flat: não expande — seleciona apenas o workspace item.
            self.list_widget.setCurrentItem(ws_item)
            self.list_widget.scrollToItem(ws_item)
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
        self,
        is_working: bool,
        is_running: bool,
        needs_decision: bool = False,
        is_plan_mode: bool = False,
    ) -> str:
        if not is_running:
            return STATE_DONE
        if is_working and is_plan_mode:
            return STATE_PLANNING
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

    _CHILD_HEIGHT = 38

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
                backend=term.backend(),
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
        is_plan_mode = term.is_plan_mode if term is not None else False
        state = self._resolve_state(is_working, is_running, needs_decision, is_plan_mode)
        widget.update_state(
            state,
            status,
            spinner_char=self.terminals_coord.current_spinner_char(),
        )
        # Layout: terminais Claude ficam dentro do bucket "Sessões Claude (N)".
        # Runners (groups) ficam como filhos diretos do workspace acima
        # do bucket. Console-scoped runners continuam aninhados no próprio
        # term_item (não afetado aqui).
        bucket = self._ensure_sessoes_bucket(ws_item)
        bucket.addChild(child)
        self.list_widget.setItemWidget(child, 0, widget)
        self._refresh_sessoes_count(ws_item)
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
        # Árvore flat: não expande o workspace (sub-itens ficam ocultos).
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
        is_plan_mode = term.is_plan_mode if term is not None else False
        state = self._resolve_state(is_working, is_running, needs_decision, is_plan_mode)
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
        if item is self.list_widget.currentItem():
            self._refresh_status_bar_console()
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
        # Aceita workspace OU bucket. Se for bucket, sobe pro workspace
        # antes de iterar terminal_items (que volta a descer).
        if ws_item.data(0, Qt.ItemDataRole.UserRole) == self._SESSOES_BUCKET_ROLE:
            real_ws = ws_item.parent()
            if real_ws is None:
                return base_title
            ws_item = real_ws
        sibling_ids: list[int] = []
        for sib in self._iter_terminal_items(ws_item):
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
        desambiguação. Barato — só N children por workspace.

        Tolera ser chamado tanto com o workspace quanto com o bucket
        (Sessões Claude) como argumento — sobe pro workspace se for bucket.
        """
        if ws_item is None:
            return
        # Se chamarem com o bucket, sobe pro workspace.
        if ws_item.data(0, Qt.ItemDataRole.UserRole) == self._SESSOES_BUCKET_ROLE:
            ws_item = ws_item.parent()
            if ws_item is None:
                return
        for sib in self._iter_terminal_items(ws_item):
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

    def _refresh_plan_usage_updated_label(self) -> None:
        """Re-renderiza o subtítulo 'atualizado há Xmin atrás' a partir
        de `_last_plan_usage_sync_at`. Chamado pelo timer de 30s e logo
        após cada sync bem-sucedido em `_refresh_plan_usage_status`."""
        from datetime import datetime

        label = getattr(self, "_context_status_updated_label", None)
        if label is None:
            return
        ts = getattr(self, "_last_plan_usage_sync_at", None)
        if ts is None:
            label.setVisible(False)
            return
        secs = max(int((datetime.now() - ts).total_seconds()), 0)
        if secs < 60:
            phrase = "atualizado agora"
        elif secs < 3600:
            mins = secs // 60
            phrase = (
                "atualizado há 1 minuto atrás"
                if mins == 1
                else f"atualizado há {mins} minutos atrás"
            )
        elif secs < 86_400:
            hours = secs // 3600
            phrase = (
                "atualizado há 1 hora atrás"
                if hours == 1
                else f"atualizado há {hours} horas atrás"
            )
        else:
            days = secs // 86_400
            phrase = (
                "atualizado há 1 dia atrás"
                if days == 1
                else f"atualizado há {days} dias atrás"
            )
        label.setText(phrase)
        label.setVisible(True)

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
        from datetime import datetime, timedelta

        from ..plan_usage_api import cooldown_remaining_seconds, fetch_plan_usage
        from ..usage_telemetry import recent_plan_usage, weekly_plan_usage

        label = getattr(self, "_context_status_label", None)
        container = getattr(self, "_context_status_container", None)
        if label is None:
            return

        updated_label = getattr(self, "_context_status_updated_label", None)

        def _set_container_visible(visible: bool) -> None:
            if container is not None:
                container.setVisible(visible)
            else:
                label.setVisible(visible)
            if not visible and updated_label is not None:
                updated_label.setVisible(False)

        def _color(p: float) -> str:
            if p < 50:
                return theme.SUCCESS
            if p < 80:
                return theme.WARNING
            return theme.DANGER

        opencode_line = ""
        opencode_tooltip = ""

        def _usage_text(text: str) -> str:
            if not opencode_line:
                return text
            return opencode_line + "<br>" + text

        def _usage_tooltip(text: str) -> str:
            if not opencode_tooltip:
                return text
            return opencode_tooltip + "\n\n" + text

        def _show_opencode_only() -> bool:
            if not opencode_line:
                return False
            label.setText(opencode_line)
            label.setToolTip(opencode_tooltip)
            self._last_plan_usage_sync_at = datetime.now()
            self._refresh_plan_usage_updated_label()
            _set_container_visible(True)
            return True

        if self.settings.ai_backend == "opencode":
            from ..usage_telemetry import aggregate_usage_opencode, format_tokens

            try:
                now = datetime.now(UTC)
                recent = aggregate_usage_opencode(now - timedelta(hours=5))
                weekly = aggregate_usage_opencode(now - timedelta(days=7))
            except Exception:  # noqa: BLE001
                log.debug("falha ao agregar uso do OpenCode", exc_info=True)
                recent = {}
                weekly = {}

            def _sum(stats_map) -> tuple[int, float, str]:
                tokens = sum(s.total_tokens for s in stats_map.values())
                cost = sum(s.cost_usd for s in stats_map.values())
                models: dict[str, int] = {}
                for stats in stats_map.values():
                    for model, count in stats.by_model.items():
                        models[model] = models.get(model, 0) + count
                top_model = max(models.items(), key=lambda kv: kv[1])[0] if models else ""
                return tokens, cost, top_model

            tokens_5h, cost_5h, model_5h = _sum(recent)
            tokens_7d, cost_7d, model_7d = _sum(weekly)
            if tokens_5h > 0 or tokens_7d > 0:
                model = model_5h or model_7d or "modelo"
                sep = f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
                chips = [
                    f"<span style='color: {theme.TEXT_FAINT};'>5h </span>"
                    f"<span style='color: {theme.SUCCESS}; font-weight: 600;'>"
                    f"{format_tokens(tokens_5h)}</span>",
                    f"<span style='color: {theme.TEXT_FAINT};'>7d </span>"
                    f"<span style='color: {theme.WARNING}; font-weight: 600;'>"
                    f"{format_tokens(tokens_7d)}</span>",
                ]
                if cost_7d > 0:
                    chips.append(
                        f"<span style='color: {theme.TEXT_FAINT};'>custo </span>"
                        f"<span style='color: {theme.TEXT_MUTED}; font-weight: 600;'>"
                        f"${cost_7d:.2f}</span>"
                    )
                opencode_line = (
                    f"<span style='color: {theme.TEXT_FAINT};'>OpenCode: </span>"
                    + sep.join(chips)
                )
                opencode_tooltip = (
                    "Uso local do OpenCode/OpenAI lido do banco SQLite do OpenCode.\n"
                    "OpenAI não expõe aqui uma porcentagem de plano equivalente ao /status do Claude; "
                    "por isso mostramos tokens/custo registrados localmente.\n"
                    f"Modelo principal: {model}\n"
                    f"5h: {format_tokens(tokens_5h)} tokens · ${cost_5h:.2f}\n"
                    f"7d: {format_tokens(tokens_7d)} tokens · ${cost_7d:.2f}"
                )

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
            # Emite cost_warning quando qualquer janela passa do threshold
            # (80% pra avisar, 95% pra crítica). dedup_key estável por
            # janela; service cuida do cooldown — não acumula popup mesmo
            # com o refresh rodando a cada 30s.
            self._maybe_emit_cost_warning(snap)
            chips: list[str] = []
            tooltip_lines: list[str] = ["Plan usage limits (via /api/oauth/usage)"]

            def _reset_phrase(reset_at):
                if reset_at is None:
                    return ""
                delta = reset_at - datetime.now(UTC)
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

            five_hour_reset_str = ""
            if snap.five_hour is not None:
                pct = snap.five_hour.utilization_pct
                five_hour_reset_str = _reset_phrase(snap.five_hour.resets_at)
                chips.append(_chip("5h", pct))
                tip = f"Sessão 5h: {pct:.0f}%"
                if snap.five_hour.resets_at is not None:
                    tip += (
                        "  ·  reseta "
                        f"{snap.five_hour.resets_at.astimezone().strftime('%H:%M')}"
                        f" ({five_hour_reset_str})"
                    )
                tooltip_lines.append(tip)

            if snap.seven_day is not None:
                pct = snap.seven_day.utilization_pct
                chips.append(_chip("semanal", pct))
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
                chips.append(_chip("Sonnet", pct))
                tooltip_lines.append(f"Semana (Sonnet): {pct:.0f}%")

            if snap.seven_day_opus is not None:
                tooltip_lines.append(
                    f"Semana (Opus): {snap.seven_day_opus.utilization_pct:.0f}%"
                )

            if chips:
                self._last_plan_usage_sync_at = datetime.now()
                self._refresh_plan_usage_updated_label()
                sync_str = self._last_plan_usage_sync_at.strftime("%H:%M:%S")
                sep = (
                    f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
                )
                prefix = f"<span style='color: {theme.TEXT_FAINT};'>Usage: </span>"
                suffix = ""
                if five_hour_reset_str:
                    suffix = (
                        f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
                        f"<span style='color: {theme.TEXT_FAINT};'>resets in "
                        f"{five_hour_reset_str}</span>"
                    )
                label.setText(_usage_text(prefix + sep.join(chips) + suffix))
                tooltip_lines.append(f"sync {sync_str} · fonte: API")
                label.setToolTip(_usage_tooltip("\n".join(tooltip_lines)))
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
            label.setText(_usage_text(
                f"<span style='color: {theme.TEXT_FAINT};'>Usage: </span>"
                f"<span style='color: {theme.WARNING};'>cooldown {mins}m</span>"
            ))
            label.setToolTip(_usage_tooltip(
                "/api/oauth/usage está rate-limited.\n"
                f"Próxima tentativa permitida em {mins} minutos "
                "(servidor manda Retry-After).\n"
                "Clique ⟳ depois disso pra sincronizar.\n"
                "Os números do fallback USD-baseado são imprecisos pra "
                "Max 5x (não há mapeamento público token→cota), por isso "
                "estão ocultos até a API responder."
            ))
            _set_container_visible(True)
            return

        # --- 2. Fallback: cálculo USD-baseado a partir dos JSONLs ---
        try:
            usage = recent_plan_usage(5 * 3600)
            weekly = weekly_plan_usage(7)
        except Exception:  # noqa: BLE001
            log.debug("falha ao agregar uso do plano", exc_info=True)
            if _show_opencode_only():
                return
            _set_container_visible(False)
            return
        if (usage.first_ts is None or usage.cost_usd <= 0) and weekly.all_cost_usd <= 0:
            if _show_opencode_only():
                return
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
            delta = reset_at - datetime.now(UTC)
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
        chips.append(_chip("semanal", all_pct))

        limit_sonnet = max(self.settings.plan_weekly_usd_limit_sonnet, 0.01)
        sonnet_pct = min(weekly.sonnet_cost_usd / limit_sonnet * 100.0, 999.0)
        chips.append(_chip("Sonnet", sonnet_pct))

        cooldown = cooldown_remaining_seconds()
        cooldown_note = ""
        if cooldown > 0:
            mins = cooldown // 60
            cooldown_note = (
                f"\nAPI /api/oauth/usage em cooldown ({mins}min restantes — "
                f"rate-limited). Reabra após esse tempo pra ver os % reais."
            )
        sep = f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
        prefix = f"<span style='color: {theme.TEXT_FAINT};'>Usage: </span>"
        suffix = ""
        if reset_5h_str:
            suffix = (
                f" <span style='color: {theme.TEXT_DISABLED};'>·</span> "
                f"<span style='color: {theme.TEXT_FAINT};'>resets in "
                f"{reset_5h_str}</span>"
            )
        label.setText(_usage_text(prefix + sep.join(chips) + suffix))
        label.setToolTip(_usage_tooltip(
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
        ))
        self._last_plan_usage_sync_at = datetime.now()
        self._refresh_plan_usage_updated_label()
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
        backend: str = "",
    ) -> None:
        terminal = self.launch_coord.launch_claude(
            workspace, resume_session_id, cwd_override, backend_override=backend
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

    def _show_ai_launch_menu(self, workspace: Workspace) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1f1f1f; color: #e6e6e6; "
            "border: 1px solid #2c2c2c; border-radius: 6px; }"
            "QMenu::item { padding: 6px 16px; }"
            "QMenu::item:selected { background: #3d6ea8; color: #fff; }"
        )
        claude_act = menu.addAction("Claude Code")
        claude_act.triggered.connect(
            lambda _=False: self._launch_claude_for(workspace, "", "", backend="claude")
        )
        opencode_act = menu.addAction("OpenCode")
        opencode_act.triggered.connect(
            lambda _=False: self._launch_claude_for(workspace, "", "", backend="opencode")
        )
        menu.exec(QCursor.pos())

    def _handoff_session(self, workspace: Workspace, session) -> None:
        self.launch_coord.handoff_session(workspace, session)

    def _launch_shell_for(self, workspace: Workspace) -> None:
        # Workspace com >1 pasta: pergunta em qual abrir o shell. Único
        # → vai direto. Cancelado → não abre.
        cwd_override: str | None = None
        if workspace.folders and len(workspace.folders) > 1:
            from PySide6.QtWidgets import QInputDialog
            chosen, ok = QInputDialog.getItem(
                self,
                "Abrir terminal",
                f"Em qual pasta de '{workspace.name}'?",
                workspace.folders,
                0,
                False,
            )
            if not ok or not chosen:
                return
            cwd_override = chosen
        terminal = self.launch_coord.launch_shell(workspace, cwd_override=cwd_override)
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
            ws = self._current_workspace()
            self.emit_workspace_error(
                "Falha ao abrir terminal",
                workspace_id=ws.id if ws else None,
                body=str(e),
            )
            return
        self._bottom_tabs.setCurrentWidget(self.terminal_host)
        self.terminal_host.setCurrentWidget(area)

    def _launch_claude_no_ctx(self, backend: str = "") -> None:
        """Abre o AI backend embutido em $HOME como nova aba na area 'sem ctx'."""
        if not backend:
            menu = QMenu(self)
            menu.addAction("Claude Code").triggered.connect(
                lambda _=False: self._launch_claude_no_ctx("claude")
            )
            menu.addAction("OpenCode").triggered.connect(
                lambda _=False: self._launch_claude_no_ctx("opencode")
            )
            menu.exec(QCursor.pos())
            return
        area = self._ensure_no_ctx_area()
        home = str(Path.home())
        short = "opencode" if backend == "opencode" else "claude"
        title = f"{short} (sem ctx) #{area.count() + 1}"
        terminal = area.add_terminal(title)
        terminal.configure_claude(home, backend=backend)
        if backend == "opencode":
            argv = [
                self.settings.opencode_command or "opencode",
                *self.settings.opencode_extra_args,
                *self.settings.opencode_session_flags(),
                home,
            ]
        else:
            argv = [
                self.settings.claude_command or "claude",
                *self.settings.claude_launch_args(),
            ]
        try:
            terminal.start_shell_command(
                argv,
                home,
                label=f"{backend} (sem ctx)",
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
                    backend=widget.backend(),
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
                    ws,
                    entry.session_id,
                    entry.cwd,
                    restored_on_startup=True,
                    backend=entry.backend,
                )
                restored += 1
            except Exception:
                log.exception("Falha ao restaurar sessão %s", entry.session_id)
        if restored:
            log.info("Restauradas %d sessão(ões) Claude da execução anterior", restored)

    def _open_plugin_palette(self) -> None:
        """Ctrl+P: dialog com comandos declarados por plugins habilitados."""
        self.plugin_coord.open_palette(self)
