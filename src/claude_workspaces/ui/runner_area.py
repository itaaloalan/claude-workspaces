"""RunnerArea — uma instância por workspace.

QTabWidget com abas de runners + header com Rodar todos / Parar todos /
Importar / Exportar / + Novo. Estado das abas persiste enquanto o app
estiver aberto, mesmo trocando de workspace.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
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

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ws = workspace
        self._running_count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header com ações de área
        header = QWidget()
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        h.addWidget(QLabel("Runners"))
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

    def running_count(self) -> int:
        return self._running_count

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
            seen_ids.add(runner.id)
            widget = existing.get(runner.id)
            if widget is None:
                widget = RunnerWidget(runner, primary)
                self._wire(widget)
            else:
                widget.update_config(runner)
            self.tabs.addTab(widget, runner.name or "(runner)")

        # Remove widgets de runners deletados.
        for rid, widget in existing.items():
            if rid not in seen_ids:
                widget.terminate()
                widget.deleteLater()

        # Toggle entre placeholder e tabs.
        self._stack.setCurrentIndex(1 if self.tabs.count() > 0 else 0)
        self._recompute_running_count()

    def _wire(self, widget: RunnerWidget) -> None:
        widget.state_changed.connect(lambda _s: self._recompute_running_count())
        widget.config_label_changed.connect(
            lambda name, w=widget: self._update_tab_text(w, name)
        )
        widget.edit_requested.connect(self._on_edit_request)
        widget.remove_requested.connect(self._on_remove_request)

    def _update_tab_text(self, widget: RunnerWidget, name: str) -> None:
        idx = self.tabs.indexOf(widget)
        if idx >= 0:
            self.tabs.setTabText(idx, name)

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
            export_runners(self._ws, path)
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
            added, replaced = import_runners(self._ws, path)
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
            added, replaced = import_runners(self._ws, path)
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
