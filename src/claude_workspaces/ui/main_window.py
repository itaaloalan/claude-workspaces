import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..launchers import LauncherError, find_app_repo_root, launch_claude_in_dir
from ..models import Workspace
from ..settings import Settings
from ..storage import load_workspaces, save_workspaces
from .settings_panel import SettingsPanel
from .terminal_area import TerminalArea
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
        self.details.tasks_changed.connect(self._persist_tasks)
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
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        if self.settings.body_splitter_sizes:
            self.body_splitter.setSizes(self.settings.body_splitter_sizes)
        else:
            self.body_splitter.setSizes([260, 920])

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
        # Ctrl+B → alternar sidebar (mais espaço pro terminal/conteúdo)
        QShortcut(QKeySequence("Ctrl+B"), self, self._toggle_sidebar)
        # Ctrl+J → alternar terminal (foco mais alto no conteúdo)
        QShortcut(QKeySequence("Ctrl+J"), self, self._toggle_terminal)
        # Ctrl+Enter → abrir Claude no workspace atual
        QShortcut(QKeySequence("Ctrl+Return"), self, self._launch_current_claude)
        # Ctrl+, → configurações (convenção)
        QShortcut(QKeySequence("Ctrl+,"), self, self._show_settings)
        # Ctrl+N → novo workspace
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_workspace)
        # Ctrl+1..9 → pular pro N-ésimo workspace visível
        for i in range(1, 10):
            QShortcut(
                QKeySequence(f"Ctrl+{i}"),
                self,
                lambda idx=i - 1: self._jump_to_workspace(idx),
            )
        # Ctrl+Tab / Ctrl+Shift+Tab → próximo/anterior workspace visível
        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: self._cycle_workspace(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: self._cycle_workspace(-1))

    def _visible_rows(self) -> list[int]:
        return [
            i for i in range(self.list_widget.count())
            if not self.list_widget.item(i).isHidden()
        ]

    def _jump_to_workspace(self, index: int) -> None:
        rows = self._visible_rows()
        if 0 <= index < len(rows):
            self.list_widget.setCurrentRow(rows[index])

    def _cycle_workspace(self, delta: int) -> None:
        rows = self._visible_rows()
        if not rows:
            return
        current = self.list_widget.currentRow()
        try:
            pos = rows.index(current)
        except ValueError:
            pos = 0
        next_pos = (pos + delta) % len(rows)
        self.list_widget.setCurrentRow(rows[next_pos])

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
        self._term_max_btn = QPushButton("⬆")
        self._term_max_btn.setToolTip("Maximizar terminal (esconder conteúdo)")
        self._term_max_btn.setFixedWidth(28)
        self._term_max_btn.setStyleSheet(btn_css)
        self._term_max_btn.clicked.connect(self._maximize_terminal)
        h.addWidget(self._term_max_btn)

        self._term_restore_btn = QPushButton("⬜")
        self._term_restore_btn.setToolTip("Restaurar layout 50/50")
        self._term_restore_btn.setFixedWidth(28)
        self._term_restore_btn.setStyleSheet(btn_css)
        self._term_restore_btn.clicked.connect(self._restore_terminal)
        h.addWidget(self._term_restore_btn)

        self._term_min_btn = QPushButton("⬇")
        self._term_min_btn.setToolTip("Minimizar terminal (Ctrl+J)")
        self._term_min_btn.setFixedWidth(28)
        self._term_min_btn.setStyleSheet(btn_css)
        self._term_min_btn.clicked.connect(self._toggle_terminal)
        h.addWidget(self._term_min_btn)

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

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.setStyleSheet(
            "QListWidget { background: transparent; border: 0; color: #e6e6e6; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 4px; color: #d0d0d0; }"
            "QListWidget::item:hover { background: #2a3142; color: #fff; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
            "QListWidget::item:selected:hover { background: #4a82c5; color: #fff; }"
        )
        layout.addWidget(self.list_widget, stretch=1)

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
            current_id = current_item.data(Qt.ItemDataRole.UserRole).id

        self.list_widget.clear()
        for ws in self.workspaces:
            item = QListWidgetItem(self._item_label(ws))
            item.setData(Qt.ItemDataRole.UserRole, ws)
            tip = ws.description or ""
            if ws.folders:
                tip = (tip + "\n\n" if tip else "") + "\n".join(ws.folders)
            if tip:
                item.setToolTip(tip)
            self.list_widget.addItem(item)

        self._apply_filter(self.top_bar.search.text() if hasattr(self, "top_bar") else "")

        if current_id:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.isHidden():
                    continue
                if item.data(Qt.ItemDataRole.UserRole).id == current_id:
                    self.list_widget.setCurrentRow(i)
                    return

        for i in range(self.list_widget.count()):
            if not self.list_widget.item(i).isHidden():
                self.list_widget.setCurrentRow(i)
                return

        self.details.show_empty()

    def _item_label(self, ws: Workspace) -> str:
        count = self._running_counts.get(ws.id, 0)
        pending = sum(1 for t in ws.tasks if not t.done)
        bits = [ws.name]
        if pending:
            bits.append(f"({pending} pend.)")
        if count > 0:
            dot = "●" if count == 1 else f"●×{count}"
            return f"{dot} " + " ".join(bits)
        return " ".join(bits)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            ws = item.data(Qt.ItemDataRole.UserRole)
            tasks_blob = " ".join(t.title for t in ws.tasks)
            haystack = (
                f"{ws.name}\n{ws.description}\n{' '.join(ws.folders)}\n{tasks_blob}"
            ).lower()
            item.setHidden(bool(needle) and needle not in haystack)
        current = self.list_widget.currentItem()
        if current and current.isHidden():
            for i in range(self.list_widget.count()):
                if not self.list_widget.item(i).isHidden():
                    self.list_widget.setCurrentRow(i)
                    return

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
        # Mudou de workspace — sempre volta pra view de detalhes
        if self.content_stack.currentIndex() != 0:
            self.content_stack.setCurrentIndex(0)
        if current is None:
            self.details.show_empty()
            self.terminal_host.setCurrentIndex(self._terminal_placeholder_idx)
            return
        ws = current.data(Qt.ItemDataRole.UserRole)
        self.details.show_workspace(ws)
        self._sync_terminal_for(ws)

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
            self._terminal_areas[ws_id] = area
            self.terminal_host.addWidget(area)
        return area

    def _launch_claude_for(
        self, workspace: Workspace, resume_session_id: str, cwd_override: str
    ) -> None:
        if not workspace.folders:
            QMessageBox.warning(self, "Workspace sem pastas", "Adicione pelo menos uma pasta.")
            return
        cwd, extras = workspace.launch_paths()
        if cwd_override:
            cwd = cwd_override
            extras = []
        argv = [self.settings.claude_command, *self.settings.claude_extra_args]
        if resume_session_id:
            argv += ["--resume", resume_session_id]
        for extra in extras:
            argv += ["--add-dir", extra]

        area = self._get_terminal_area(workspace)
        self.terminal_host.setCurrentWidget(area)
        title = "claude (resume)" if resume_session_id else "claude"
        title = f"{title} #{area.count() + 1}"
        terminal = area.add_terminal(title)
        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=f"claude — {workspace.name}",
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir Claude embutido")
            QMessageBox.warning(self, "Falha", str(e))

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

    def _persist_tasks(self, workspace: Workspace) -> None:
        # Workspace dentro de self.workspaces é a mesma instância referenciada
        # pelos itens (refresh_list passa o próprio objeto via UserRole), então
        # só precisa salvar e atualizar o badge.
        save_workspaces(self.workspaces)
        self._refresh_item_label(workspace.id)

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
            self.refresh_list()

    def edit_workspace(self, workspace: Workspace) -> None:
        dialog = WorkspaceDialog(workspace=workspace, parent=self)
        if dialog.exec():
            updated = dialog.workspace()  # mesma id, tasks preservadas
            idx = next(
                (i for i, w in enumerate(self.workspaces) if w.id == workspace.id),
                None,
            )
            if idx is None:
                return
            self.workspaces[idx] = updated
            save_workspaces(self.workspaces)
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
