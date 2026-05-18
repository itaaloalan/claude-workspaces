"""RunnerArea — uma instância por workspace.

QTabWidget com abas de runners + header com Rodar todos / Parar todos /
Importar / Exportar / + Novo. Estado das abas persiste enquanto o app
estiver aberto, mesmo trocando de workspace.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import RunnerConfig, Workspace
from ..settings import Settings
from .runner_widget import RunnerWidget


class RunnerArea(QWidget):
    """Container das abas de runners de um workspace.

    Signals:
        runners_changed: emitido quando o conjunto de runners do workspace
            mudar (criar/editar/remover/importar) — main_window persiste.
        running_count_changed(int): número de runners atualmente em estado
            "running" (pra bolinha verde na sidebar).
    """

    runners_changed = Signal()
    running_count_changed = Signal(int)
    runner_state_changed = Signal(str, str)  # runner_id, state

    def __init__(
        self,
        workspace: Workspace,
        settings: Settings | None = None,
        parent: QWidget | None = None,
        console_session_id: str = "",
    ) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._settings = settings or Settings()
        self._running_count = 0
        # "" → escopo workspace (mostra apenas runners sem console_session_id).
        # Quando preenchido, é o session_id do console Claude dono deste painel
        # e mostra apenas runners daquele console.
        self._console_session_id = console_session_id

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header com ações de área
        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        label = "Runners (console)" if console_session_id else "Runners"
        h.addWidget(QLabel(label))
        h.addStretch()

        self._run_all_btn = QPushButton("▶ Rodar todos")
        self._run_all_btn.clicked.connect(self._run_all)
        h.addWidget(self._run_all_btn)

        self._stop_all_btn = QPushButton("■ Parar todos")
        self._stop_all_btn.clicked.connect(self._stop_all)
        h.addWidget(self._stop_all_btn)

        self._import_btn = QPushButton("Importar")
        self._import_btn.clicked.connect(self._import_runners)
        h.addWidget(self._import_btn)

        self._export_btn = QPushButton("Exportar")
        self._export_btn.clicked.connect(self._export_runners)
        h.addWidget(self._export_btn)

        self._reload_btn = QPushButton("↻ Recarregar runners")
        self._reload_btn.setToolTip(
            "Importa runners gerados pelo Claude a partir do rascunho salvo "
            "em ~/.config/claude-workspaces/runner-drafts/<workspace>.json"
        )
        self._reload_btn.clicked.connect(self._reload_from_draft)
        h.addWidget(self._reload_btn)

        self._add_btn = QPushButton("+ Novo")
        self._add_btn.clicked.connect(self._open_add_menu)
        h.addWidget(self._add_btn)

        outer.addWidget(header)

        # Stack: placeholder quando não há runners; tabs quando tem.
        self._stack = QStackedWidget()
        self._empty = QLabel(
            "Nenhum runner configurado para este workspace.\n"
            "Clique em '+ Novo' para adicionar — em branco ou gerar com Claude."
        )
        self._empty.setStyleSheet("color: #777; padding: 24px;")
        self._empty.setWordWrap(True)
        self._stack.addWidget(self._empty)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self._stack.addWidget(self.tabs)

        outer.addWidget(self._stack, stretch=1)

        # Callback definido por main_window para abrir o RunnerEditDialog
        # e/ou disparar a geração via Claude. Mantém RunnerArea desacoplada
        # da MainWindow.
        self._edit_handler: Callable[[RunnerConfig | None], None] | None = None
        self._generate_handler: Callable[[], None] | None = None

        self._refresh_from_workspace()

    # ---- API pública -----------------------------------------------------

    def set_edit_handler(
        self, handler: Callable[[RunnerConfig | None], None]
    ) -> None:
        self._edit_handler = handler

    def set_generate_handler(self, handler: Callable[[], None]) -> None:
        self._generate_handler = handler

    def workspace(self) -> Workspace:
        return self._ws

    def console_session_id(self) -> str:
        return self._console_session_id

    def set_console_session_id(self, sid: str) -> None:
        """Atualiza o session_id que este painel filtra. Usado pelo
        TerminalWidget quando o session_id do Claude é resolvido tarde
        (sessões novas só ganham id depois do primeiro flush do JSONL)."""
        if sid == self._console_session_id:
            return
        # Migra runners pendentes (criados com sid antigo "") para o novo sid.
        if self._console_session_id == "" and sid:
            # Não migra automático — o painel embutido deve nascer já com sid
            # ou esperar resolução. Apenas atualiza o filtro.
            pass
        self._console_session_id = sid
        self._refresh_from_workspace()

    def runners_in_scope(self) -> list[RunnerConfig]:
        return [r for r in self._ws.runners if self._matches_scope(r)]

    def _matches_scope(self, runner: RunnerConfig) -> bool:
        return (runner.console_session_id or "") == self._console_session_id

    def running_count(self) -> int:
        return self._running_count

    def widget_for(self, runner_id: str) -> RunnerWidget | None:
        """Retorna o RunnerWidget de um runner pelo id, ou None."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.runner_id() == runner_id:
                return w
        return None

    def focus_runner(self, runner_id: str) -> bool:
        """Foca a aba do runner pelo id. Retorna True se achou."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.runner_id() == runner_id:
                self.tabs.setCurrentIndex(i)
                return True
        return False

    def close_all(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget):
                w.terminate()

    def refresh(self) -> None:
        """Reconstrói as abas a partir do estado atual de `workspace.runners`.

        Mantém widgets em execução para runners cujo id ainda existe.
        """
        self._refresh_from_workspace()

    # ---- internals -------------------------------------------------------

    def _refresh_from_workspace(self) -> None:
        existing: dict[str, RunnerWidget] = {}
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget):
                existing[w.runner_id()] = w

        # Limpa abas mas não fecha widgets ainda — vamos reaproveitar.
        while self.tabs.count():
            self.tabs.removeTab(0)

        primary = self._ws.primary_folder or ""
        seen_ids: set[str] = set()
        for runner in self._ws.runners:
            if not self._matches_scope(runner):
                continue
            seen_ids.add(runner.id)
            widget = existing.get(runner.id)
            if widget is None:
                widget = RunnerWidget(runner, primary, settings=self._settings)
                self._wire(widget)
            else:
                widget.update_config(runner)
            self.tabs.addTab(widget, runner.name or "(runner)")
            self._update_tab_color(widget)

        # Remove widgets de runners deletados.
        for rid, widget in existing.items():
            if rid not in seen_ids:
                widget.terminate()
                widget.deleteLater()

        # Toggle entre placeholder e tabs.
        self._stack.setCurrentIndex(1 if self.tabs.count() > 0 else 0)
        self._recompute_running_count()

    def _wire(self, widget: RunnerWidget) -> None:
        widget.state_changed.connect(
            lambda _s, w=widget: self._on_runner_state(w)
        )
        widget.config_label_changed.connect(
            lambda name, w=widget: self._update_tab_text(w, name)
        )
        widget.edit_requested.connect(self._on_edit_request)
        widget.remove_requested.connect(self._on_remove_request)

    def _on_runner_state(self, widget: RunnerWidget) -> None:
        self._recompute_running_count()
        self._update_tab_color(widget)
        self.runner_state_changed.emit(widget.runner_id(), widget.current_state())

    def _update_tab_text(self, widget: RunnerWidget, name: str) -> None:
        idx = self.tabs.indexOf(widget)
        if idx >= 0:
            self.tabs.setTabText(idx, name)
            self._update_tab_color(widget)

    def _update_tab_color(self, widget: RunnerWidget) -> None:
        idx = self.tabs.indexOf(widget)
        if idx < 0:
            return
        # Verde quando rodando, vermelho discreto quando saiu com
        # erro/exited inesperado; senão herda do tema (None).
        state = widget.current_state()
        color = None
        if state == "running":
            color = QColor("#4ade80")  # verde-claro
        elif state == "error":
            color = QColor("#f87171")
        bar = self.tabs.tabBar()
        if color is None:
            bar.setTabTextColor(idx, QColor())  # reset
        else:
            bar.setTabTextColor(idx, color)

    def _recompute_running_count(self) -> None:
        count = 0
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.is_running():
                count += 1
        if count != self._running_count:
            self._running_count = count
            self.running_count_changed.emit(count)

    # ---- ações de área ---------------------------------------------------

    def _run_all(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.config().enabled and not w.is_running():
                w.start()

    def _stop_all(self) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.is_running():
                w.stop()

    def _open_add_menu(self) -> None:
        menu = QMenu(self)
        a_blank = menu.addAction("Em branco")
        a_blank.triggered.connect(lambda: self._edit_handler and self._edit_handler(None))
        a_gen = menu.addAction("Gerar com Claude")
        a_gen.triggered.connect(lambda: self._generate_handler and self._generate_handler())
        menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))

    def _on_edit_request(self, runner_id: str) -> None:
        if self._edit_handler is None:
            return
        for r in self._ws.runners:
            if r.id == runner_id:
                self._edit_handler(r)
                return

    def _on_remove_request(self, runner_id: str) -> None:
        for i, r in enumerate(self._ws.runners):
            if r.id == runner_id:
                if (
                    QMessageBox.question(
                        self,
                        "Remover runner",
                        f"Remover o runner '{r.name}'?",
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
                self._ws.runners.pop(i)
                self.runners_changed.emit()
                self._refresh_from_workspace()
                return

    # ---- import/export ---------------------------------------------------

    def _export_runners(self) -> None:
        from ..runners_io import export_runners

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar runners",
            f"{self._ws.name}-runners.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            # Export sempre limita ao escopo deste painel — workspace
            # exporta só workspace-scoped; painel de console exporta só
            # daquele console (sem o session_id pra ser portável).
            export_runners(
                self._ws, path, console_session_id=self._console_session_id
            )
        except OSError as e:
            QMessageBox.critical(self, "Erro ao exportar", str(e))

    def _reload_from_draft(self) -> None:
        from ..runners_io import import_runners
        from ..services.runner_prompt import pending_runner_path

        path = pending_runner_path(self._ws)
        if not path.exists():
            QMessageBox.information(
                self,
                "Sem rascunho",
                f"Nenhum rascunho encontrado em:\n{path}\n\n"
                "Use '+ Novo → Gerar com Claude' e aguarde o Claude "
                "salvar o arquivo antes de recarregar.",
            )
            return
        try:
            added, replaced = import_runners(
                self._ws, path, console_session_id=self._console_session_id
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erro ao importar rascunho", str(e))
            return
        self.runners_changed.emit()
        self._refresh_from_workspace()
        QMessageBox.information(
            self,
            "Rascunho importado",
            f"Adicionados: {added}. Substituídos: {replaced}.",
        )

    def _import_runners(self) -> None:
        from ..runners_io import import_runners

        path, _ = QFileDialog.getOpenFileName(
            self, "Importar runners", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            added, replaced = import_runners(
                self._ws, path, console_session_id=self._console_session_id
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erro ao importar", str(e))
            return
        self.runners_changed.emit()
        self._refresh_from_workspace()
        QMessageBox.information(
            self,
            "Importação concluída",
            f"Adicionados: {added}. Substituídos: {replaced}.",
        )
