import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
from ..storage import load_workspaces, save_workspaces
from .memory_panel import MemoryPanel
from .right_dock import RightDock
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
from .workspace_details import WorkspaceDetailsPanel
from .workspace_dialog import WorkspaceDialog

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claude Workspaces")

        self.settings = Settings.load()
        self.workspaces: list[Workspace] = load_workspaces()
        # Migração silenciosa: se algum workspace veio sem id (arquivo
        # antigo), salva de volta com ids preenchidos pelo from_dict.
        self._migrate_ids_if_needed()

        self._running_counts: dict[str, int] = {}  # key=workspace.id
        self._terminal_areas: dict[str, TerminalArea] = {}  # key=workspace.id
        self._terminal_placeholder_idx: int = 0
        self._sidebar_last_size: int = 260
        self._terminal_last_size: int = 420
        self._content_last_size: int = 420
        # Tree items dos terminais ativos (children dos workspace items)
        # key = id() do TerminalWidget; value = QTreeWidgetItem
        self._terminal_tree_items: dict[int, QTreeWidgetItem] = {}
        # Estado de atividade pra animar o spinner
        # key = tab_id; value = (status, is_working, title)
        self._terminal_activity: dict[int, tuple[str, bool, str]] = {}
        self._spinner_frame: int = 0
        # Cache de texto de sessões pro filtro (lazy, key=ws.id)
        self._session_text_cache: dict[str, str] = {}
        # Inbox de consoles aguardando atenção (working → idle transitions)
        # key = tab_id; value = {workspace_id, title, status, when}
        self._inbox: dict[int, dict] = {}

        self._build_ui()
        self._restore_geometry()
        self.refresh_list()

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
        self.right_splitter.setChildrenCollapsible(True)
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
        self.content_stack.addWidget(self.details)

        self.settings_panel = SettingsPanel(self.settings)
        self.content_stack.addWidget(self.settings_panel)
        self.content_stack.setMinimumHeight(0)

        self.right_splitter.addWidget(self.content_stack)

        # Painel do terminal: barra de controle (maximizar/minimizar)
        # + stack de TerminalAreas por workspace
        self._terminal_pane = self._build_terminal_pane()
        self.right_splitter.addWidget(self._terminal_pane)

        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)
        if self.settings.right_splitter_sizes:
            self.right_splitter.setSizes(self.settings.right_splitter_sizes)
        else:
            self.right_splitter.setSizes([420, 380])

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

        outer.addWidget(self.body_splitter, stretch=1)
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
        # Busca em sessões
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self._show_sessions_search)
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

    def _toggle_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        if not sizes:
            return
        if sizes[1] > 0:
            self._terminal_last_size = sizes[1]
            self.right_splitter.setSizes([sum(sizes), 0])
        else:
            target = self._terminal_last_size or 420
            self.right_splitter.setSizes([max(sum(sizes) - target, 200), target])
        self._refresh_terminal_btns()
        self._schedule_layout_save()

    def _maximize_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        total = sum(sizes) or 800
        if sizes[0] > 0:
            self._content_last_size = sizes[0]
        self.right_splitter.setSizes([0, total])
        self._refresh_terminal_btns()
        self._schedule_layout_save()

    def _restore_terminal(self) -> None:
        sizes = self.right_splitter.sizes()
        total = sum(sizes) or 800
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
        terminal_visible = sizes[1] > 0
        self._term_max_btn.setEnabled(content_visible)
        self._term_min_btn.setEnabled(terminal_visible)
        # Restaurar só faz sentido se algum lado está colapsado
        self._term_restore_btn.setEnabled(not (content_visible and terminal_visible))

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
        return current.data(Qt.ItemDataRole.UserRole)

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
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        # Versão simples por enquanto — listar todos os arquivos é caro
        # em repos grandes. Pedimos um padrão e usamos find/grep.
        pattern, ok = QInputDialog.getText(
            self,
            "Quick open",
            f"Nome (ou parte) do arquivo em {Path(ws.folders[0]).name}:",
        )
        if not ok or not pattern.strip():
            return
        pattern = pattern.strip()
        import subprocess
        matches: list[str] = []
        for folder in ws.folders:
            try:
                r = subprocess.run(
                    ["git", "ls-files"],
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        if pattern.lower() in line.lower():
                            matches.append(str(Path(folder) / line))
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        if not matches:
            QMessageBox.information(
                self, "Quick open", f"Nenhum arquivo casa com '{pattern}'"
            )
            return
        choice, ok = QInputDialog.getItem(
            self, "Quick open", f"{len(matches)} match(es):",
            matches[:200], 0, False,
        )
        if ok and choice:
            self._open_file_in_editor(choice)

    def _open_folder_in_file_manager(self) -> None:
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        import subprocess
        try:
            subprocess.Popen(["xdg-open", ws.folders[0]])
        except FileNotFoundError:
            QMessageBox.warning(self, "xdg-open ausente", "Instale xdg-utils.")

    def _copy_primary_folder(self) -> None:
        from PySide6.QtGui import QGuiApplication
        ws = self._current_workspace()
        if not ws or not ws.folders:
            return
        QGuiApplication.clipboard().setText(ws.folders[0])

    def _show_shortcuts(self) -> None:
        from .shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

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

    def _build_right_dock(self) -> QWidget:
        dock = RightDock()
        dock.setStyleSheet("background: #141414;")
        collapsed = self.settings.right_dock_collapsed or {}

        # Git
        git_panel = self.details.git_panel()
        dock.add_panel(
            "git", "Git", git_panel,
            open_=not collapsed.get("git", False),
        )

        # Memória do workspace (CLAUDE.md)
        self._memory_panel = MemoryPanel()
        dock.add_panel(
            "memory", "Memória", self._memory_panel,
            open_=not collapsed.get("memory", True),
        )

        # Skills (default fechado)
        self._skills_panel = SkillsPanel()
        dock.add_panel(
            "skills", "Skills", self._skills_panel,
            open_=not collapsed.get("skills", True),
        )

        dock.panel_toggled.connect(self._on_dock_toggled)
        return dock

    def _on_dock_toggled(self, panel_id: str, is_open: bool) -> None:
        # Persiste estado (chave 'collapsed' = inverso de 'open')
        self.settings.right_dock_collapsed[panel_id] = not is_open
        self._schedule_layout_save()

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

        # Timer pra animar o spinner dos terminais em "working"
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._tick_spinner)

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
        self._terminal_tree_items.clear()

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
        for ws_id, area in self._terminal_areas.items():
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
                    self._terminal_activity.get(tab_id, ("", False, base_title))[0],
                    self._terminal_activity.get(tab_id, ("", False, base_title))[1],
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
        count = self._running_counts.get(ws.id, 0)
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
        """Concat dos previews das últimas sessões do Claude desse workspace.
        Cacheado por ws.id — invalidado em refresh_list e em CRUD do workspace."""
        if ws.id in self._session_text_cache:
            return self._session_text_cache[ws.id]
        text = ""
        if ws.folders:
            try:
                from ..claude_sessions import list_sessions_for_paths
                cwd, _ = ws.launch_paths()
                paths = list({cwd, *ws.folders})
                sessions = list_sessions_for_paths(paths, limit=15)
                text = " ".join(s.preview for s in sessions if s.preview)
            except Exception:
                text = ""
        self._session_text_cache[ws.id] = text
        return text

    def _invalidate_session_cache(self, ws_id: str | None = None) -> None:
        if ws_id is None:
            self._session_text_cache.clear()
        else:
            self._session_text_cache.pop(ws_id, None)

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
            self._running_counts.pop(workspace_id, None)
        else:
            self._running_counts[workspace_id] = count
        self._refresh_item_label(workspace_id)

    # ---------- seleção / settings ----------

    def _on_selection_changed(self, current, _previous) -> None:
        if self.content_stack.currentIndex() != 0:
            self.content_stack.setCurrentIndex(0)
        if current is None:
            self.details.show_empty()
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)
            self._skills_panel.set_workspace(None)
            self._memory_panel.set_workspace(None)
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
        self._skills_panel.set_workspace(ws)
        self._memory_panel.set_workspace(ws)
        self._sync_terminal_for(ws)

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
        tab_id = data
        area = self._terminal_areas.get(pdata.id)
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
        self.content_stack.setCurrentWidget(self.settings_panel)

    def _show_workspaces(self) -> None:
        self.content_stack.setCurrentIndex(0)
        current = self.list_widget.currentItem()
        if current:
            ws = current.data(Qt.ItemDataRole.UserRole)
            self.details.show_workspace(ws)
            self._sync_terminal_for(ws)

    # ---------- terminal ----------

    def _sync_terminal_for(self, workspace: Workspace) -> None:
        area = self._terminal_areas.get(workspace.id)
        if area is not None:
            self.terminal_host.setCurrentWidget(area)
        else:
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)

    def _get_terminal_area(self, workspace: Workspace) -> TerminalArea:
        area = self._terminal_areas.get(workspace.id)
        if area is None:
            area = TerminalArea()
            ws_id = workspace.id
            area.running_count_changed.connect(
                lambda c, wid=ws_id: self._on_workspace_running(wid, c)
            )
            area.tab_activity_changed.connect(
                lambda tab_id, title, status, working, running, wid=ws_id:
                    self._on_tab_activity(wid, tab_id, title, status, working, running)
            )
            area.tab_removed.connect(self._on_tab_removed)
            area.tabs.currentChanged.connect(
                lambda idx, a=area: self._on_terminal_tab_focused(a, idx)
            )
            self._terminal_areas[ws_id] = area
            self.terminal_host.addWidget(area)
        return area

    def _on_terminal_tab_focused(self, area: TerminalArea, idx: int) -> None:
        if idx < 0:
            return
        widget = area.tabs.widget(idx)
        if widget is None:
            return
        tab_id = id(widget)
        if self._inbox.pop(tab_id, None) is not None:
            self._refresh_inbox_badge()

    def _on_tab_activity(
        self,
        workspace_id: str,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        prev_status, prev_working, prev_title = self._terminal_activity.get(
            tab_id, ("", False, title)
        )
        self._terminal_activity[tab_id] = (status, is_working, title)

        # Detecção de "precisa de atenção": estava working e agora não está
        # (mas ainda rodando). Adiciona ao inbox global.
        if prev_working and not is_working and is_running:
            self._inbox[tab_id] = {
                "workspace_id": workspace_id,
                "title": title,
                "status": status,
            }
            self._refresh_inbox_badge()
        elif is_working and tab_id in self._inbox:
            # Voltou a trabalhar — sai do inbox
            self._inbox.pop(tab_id, None)
            self._refresh_inbox_badge()
        elif not is_running and tab_id in self._inbox:
            # Terminou — sai do inbox
            self._inbox.pop(tab_id, None)
            self._refresh_inbox_badge()

        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is None:
            return
        if tab_id in self._terminal_tree_items:
            self._update_terminal_child(tab_id, title, status, is_working, is_running)
        else:
            self._add_terminal_child(
                ws_item, tab_id, title, status, is_working, is_running
            )
        any_working = any(w for _, w, _ in self._terminal_activity.values())
        if any_working and not self._spinner_timer.isActive():
            self._spinner_timer.start()
        elif not any_working and self._spinner_timer.isActive():
            self._spinner_timer.stop()

    def _refresh_inbox_badge(self) -> None:
        self.top_bar.set_inbox_count(len(self._inbox))

    def _show_inbox(self) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu
        if not self._inbox:
            menu = QMenu(self)
            empty = QAction("(nenhum console aguardando)", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            menu.exec_(self.top_bar.mapToGlobal(self.top_bar.rect().bottomRight()))
            return
        menu = QMenu(self)
        for tab_id, info in list(self._inbox.items()):
            ws = next(
                (w for w in self.workspaces if w.id == info["workspace_id"]),
                None,
            )
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
        clear.triggered.connect(self._clear_inbox)
        menu.addAction(clear)
        # Posiciona logo abaixo do bell
        anchor = self.top_bar._inbox_btn
        menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _clear_inbox(self) -> None:
        self._inbox.clear()
        self._refresh_inbox_badge()

    def _focus_tab_from_inbox(self, workspace_id: str, tab_id: int) -> None:
        self._inbox.pop(tab_id, None)
        self._refresh_inbox_badge()
        ws_item = self._find_workspace_item(workspace_id)
        if ws_item is not None:
            self.list_widget.setCurrentItem(ws_item)
        area = self._terminal_areas.get(workspace_id)
        if area is None:
            return
        for i in range(area.tabs.count()):
            if id(area.tabs.widget(i)) == tab_id:
                area.tabs.setCurrentIndex(i)
                self.terminal_host.setCurrentWidget(area)
                break

    def _on_tab_removed(self, tab_id: int) -> None:
        item = self._terminal_tree_items.pop(tab_id, None)
        self._terminal_activity.pop(tab_id, None)
        if self._inbox.pop(tab_id, None) is not None:
            self._refresh_inbox_badge()
        if item is not None and item.parent() is not None:
            item.parent().removeChild(item)
        if not any(w for _, w, _ in self._terminal_activity.values()):
            self._spinner_timer.stop()

    SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def _resolve_state(self, is_working: bool, is_running: bool) -> str:
        if not is_running:
            return STATE_DONE
        if is_working:
            return STATE_WORKING
        return STATE_IDLE

    def _terminal_widget_for(self, tab_id: int) -> TerminalWidget | None:
        for area in self._terminal_areas.values():
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
        spinner = self.SPINNER_FRAMES[self._spinner_frame % len(self.SPINNER_FRAMES)]
        widget.update_state(
            self._resolve_state(is_working, is_running), status, spinner_char=spinner
        )
        ws_item.addChild(child)
        self.list_widget.setItemWidget(child, 0, widget)
        ws_item.setExpanded(True)
        self._terminal_tree_items[tab_id] = child

    def _update_terminal_child(
        self,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        item = self._terminal_tree_items.get(tab_id)
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
        spinner = self.SPINNER_FRAMES[self._spinner_frame % len(self.SPINNER_FRAMES)]
        widget.update_state(
            self._resolve_state(is_working, is_running), status, spinner_char=spinner
        )

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        for tab_id, (status, working, title) in list(self._terminal_activity.items()):
            if working:
                self._update_terminal_child(tab_id, title, status, True, True)

    def _launch_claude_for(
        self, workspace: Workspace, resume_session_id: str, cwd_override: str
    ) -> None:
        if not workspace.folders:
            QMessageBox.warning(self, "Workspace sem pastas", "Adicione pelo menos uma pasta.")
            return
        cwd, extras = workspace.launch_paths()
        worktree_label = ""
        if cwd_override:
            cwd = cwd_override
            extras = []
        elif not resume_session_id:
            # Resume não passa pelo dialog (preserva a sessão exata)
            from ..git_worktree import add_worktree
            from .launch_claude_dialog import LaunchClaudeDialog
            dialog = LaunchClaudeDialog(workspace, self.settings, parent=self)
            if not dialog.exec():
                return
            selected = dialog.result_folders()
            if not selected:
                return
            cwd = selected[0]
            extras = selected[1:]
            if dialog.result_isolate():
                branch = dialog.result_branch()
                create = dialog.result_create_branch()
                base = dialog.result_base_branch() or None if create else None
                if not branch:
                    QMessageBox.warning(
                        self, "Branch inválida", "Escolha um nome de branch."
                    )
                    return
                ok, msg, dest = add_worktree(cwd, branch, base, create_branch=create)
                if not ok:
                    QMessageBox.warning(
                        self,
                        "Falha ao criar worktree",
                        f"Não consegui criar o worktree:\n\n{msg}",
                    )
                    return
                cwd = str(dest)
                worktree_label = f" · {branch}"

        argv = [self.settings.claude_command, *self.settings.claude_extra_args]
        if resume_session_id:
            argv += ["--resume", resume_session_id]
        for extra in extras:
            argv += ["--add-dir", extra]

        area = self._get_terminal_area(workspace)
        self.terminal_host.setCurrentWidget(area)
        title = "claude (resume)" if resume_session_id else "claude"
        title = f"{title} #{area.count() + 1}{worktree_label}"
        terminal = area.add_terminal(title)
        # Dá pra terminal saber que é Claude (cwd + resume id), pra ele
        # tentar achar o título da sessão (1º user prompt) e mostrar no tree
        terminal.configure_claude(cwd, resume_session_id or None)
        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=f"claude — {workspace.name}{worktree_label}",
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir Claude embutido")
            QMessageBox.warning(self, "Falha", str(e))
            return
        # JSONL da nova sessão aparece em ~1-3s; pede refresh dos cards
        # de Sessões recentes (workspace_details agenda dois QTimer)
        self.details.refresh_sessions_soon()

    def _handoff_session(self, workspace: Workspace, session) -> None:
        from PySide6.QtGui import QGuiApplication

        from .handoff_dialog import HandoffDialog
        dialog = HandoffDialog(session, parent=self)
        if not dialog.exec():
            return
        briefing = dialog.briefing()
        if not briefing:
            return
        QGuiApplication.clipboard().setText(briefing)
        # Abre um novo Claude no workspace (passa pelo LaunchClaudeDialog normal,
        # respeitando defaults). Depois agenda envio do briefing após 4s pro
        # Claude estar pronto pra receber input.
        before_count = 0
        area_before = self._terminal_areas.get(workspace.id)
        if area_before is not None:
            before_count = area_before.tabs.count()
        self._launch_claude_for(workspace, "", "")
        area_after = self._terminal_areas.get(workspace.id)
        if area_after is None or area_after.tabs.count() == before_count:
            return  # usuário cancelou o LaunchClaudeDialog
        new_terminal = area_after.tabs.widget(area_after.tabs.count() - 1)
        if not isinstance(new_terminal, TerminalWidget):
            return
        # Envia o briefing como input ~4s depois (espera Claude inicializar)
        QTimer.singleShot(
            4000, lambda: self._send_to_terminal(new_terminal, briefing)
        )

    def _send_to_terminal(self, terminal: "TerminalWidget", text: str) -> None:
        if not terminal.session.is_running():
            log.warning("Terminal não está rodando, abortando envio do briefing")
            return
        try:
            payload = (text + "\n").encode("utf-8")
            terminal.session.write(payload)
        except Exception:
            log.exception("Falha ao enviar briefing pro terminal")

    def _launch_shell_for(self, workspace: Workspace) -> None:
        if not workspace.folders:
            return
        cwd, _ = workspace.launch_paths()
        area = self._get_terminal_area(workspace)
        self.terminal_host.setCurrentWidget(area)
        terminal = area.add_terminal(f"shell #{area.count() + 1}")
        try:
            terminal.start_interactive_shell(
                cwd,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir shell embutido")
            QMessageBox.warning(self, "Falha", str(e))

    def _cleanup_terminal_for(self, workspace_id: str) -> None:
        area = self._terminal_areas.pop(workspace_id, None)
        if area is None:
            return
        area.close_all()
        self.terminal_host.removeWidget(area)
        area.deleteLater()
        self._running_counts.pop(workspace_id, None)
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
        if dialog.exec():
            ws = dialog.workspace()
            if not ws.name:
                QMessageBox.warning(self, "Workspace inválido", "O nome não pode ficar vazio.")
                return
            self.workspaces.append(ws)
            save_workspaces(self.workspaces)
            # Aplicar template (CLAUDE.md) se marcado
            tpl = dialog.selected_template()
            if (
                dialog.init_claude_md()
                and tpl is not None
                and tpl.claude_md
                and ws.folders
            ):
                self._apply_template_claude_md(ws, tpl)
            self.refresh_list()

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
            QMessageBox.warning(
                self,
                "Falha ao gravar CLAUDE.md",
                str(e),
            )

    def edit_workspace(self, workspace: Workspace) -> None:
        dialog = WorkspaceDialog(workspace=workspace, parent=self)
        if dialog.exec():
            updated = dialog.workspace()  # mesma id
            idx = next(
                (i for i, w in enumerate(self.workspaces) if w.id == workspace.id),
                None,
            )
            if idx is None:
                return
            self.workspaces[idx] = updated
            save_workspaces(self.workspaces)
            self._invalidate_session_cache(updated.id)
            self.refresh_list()
            # Reapresenta com os novos dados (mesmo id = mesmo terminal area)
            self.details.show_workspace(updated)

    def delete_workspace(self, workspace: Workspace) -> None:
        reply = QMessageBox.question(
            self,
            "Remover workspace",
            f"Remover o workspace '{workspace.name}'?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.workspaces = [w for w in self.workspaces if w.id != workspace.id]
            save_workspaces(self.workspaces)
            self._cleanup_terminal_for(workspace.id)
            self._invalidate_session_cache(workspace.id)
            self.refresh_list()

    # ---------- persistência ----------

    def _migrate_ids_if_needed(self) -> None:
        # from_dict já preenche id ausente; só precisamos persistir se algo mudou.
        # Detectamos pela presença do campo no arquivo original — mas como
        # comparar é caro, salva sempre quando há ao menos 1 workspace.
        # Custo: 1 write inicial, garantia de migração estável.
        if self.workspaces:
            save_workspaces(self.workspaces)

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
        super().closeEvent(event)
