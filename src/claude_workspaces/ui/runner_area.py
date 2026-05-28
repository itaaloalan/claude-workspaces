"""RunnerArea — uma instância por workspace.

QTabWidget com abas de runners + header com Rodar todos / Parar todos /
Importar / Exportar / + Novo. Estado das abas persiste enquanto o app
estiver aberto, mesmo trocando de workspace.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
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
from . import theme
from .runner_widget import RunnerWidget

_RUNNER_BTN_QSS = (
    "QPushButton { background: rgba(255,255,255,7); color: #c8c8c8; "
    "border: 1px solid rgba(255,255,255,18); border-radius: 6px; "
    "padding: 4px 10px; font-size: 11px; }"
    "QPushButton:hover { background: rgba(255,255,255,11); "
    "border-color: rgba(90,195,90,90); color: #e6e6e6; }"
    "QPushButton:disabled { color: #555; border-color: rgba(255,255,255,10); }"
)

_RUNNER_TABS_QSS = (
    "QTabWidget::pane { border: 0; background: #101010; }"
    "QTabBar::tab { background: #171717; color: #9a9a9a; "
    "border: 1px solid #282828; border-bottom: 0; padding: 6px 12px; "
    "margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }"
    "QTabBar::tab:selected { background: #101010; color: #e6e6e6; "
    "border-color: rgba(90,195,90,80); }"
    "QTabBar::tab:hover:!selected { color: #d0d0d0; background: #1d1d1d; }"
)


def _logger():
    import logging
    return logging.getLogger(__name__)


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
    runner_url_changed = Signal(str, str)    # runner_id, url ("" = desconhecido)
    runner_status_changed = Signal(str, str)  # runner_id, status_label

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

        # RunnerWidget (filha) tem toolbar com muitos botões; propagaria
        # mínimo de largura >600px pra cima até a janela, causando scroll
        # horizontal ao abrir o painel. Quebra essa propagação aqui.
        self.setMinimumWidth(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header compacto: título | espaço | ▶ | ■ | ⋯
        header = QWidget()
        header.setStyleSheet(
            "QWidget { background: #151515; border-bottom: 1px solid #242424; }"
            "QLabel { background: transparent; border: 0; }"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        label = "Runners do console" if console_session_id else "Runners"
        title = QLabel(label)
        title.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; font-weight: 700;"
        )
        h.addWidget(title)
        h.addStretch(1)

        self._run_all_btn = QPushButton("▶ Rodar todos")
        self._run_all_btn.setStyleSheet(_RUNNER_BTN_QSS)
        self._run_all_btn.clicked.connect(self._run_all)
        h.addWidget(self._run_all_btn)

        self._stop_all_btn = QPushButton("■ Parar todos")
        self._stop_all_btn.setStyleSheet(_RUNNER_BTN_QSS)
        self._stop_all_btn.clicked.connect(self._stop_all)
        h.addWidget(self._stop_all_btn)

        self._more_btn = QPushButton("⋯")
        self._more_btn.setStyleSheet(_RUNNER_BTN_QSS)
        self._more_btn.setFixedWidth(32)
        self._more_btn.setToolTip("Mais ações")
        self._more_btn.clicked.connect(self._open_more_menu)
        h.addWidget(self._more_btn)

        outer.addWidget(header)

        # Stack: placeholder quando não há runners; tabs quando tem.
        self._stack = QStackedWidget()
        self._empty = QLabel(
            "Nenhum runner configurado para este workspace.\n"
            "Clique em '+ Novo' para adicionar — em branco ou gerar com IA."
        )
        self._empty.setStyleSheet("color: #777; padding: 24px;")
        self._empty.setWordWrap(True)
        self._stack.addWidget(self._empty)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(_RUNNER_TABS_QSS)
        # Quando o user arrasta uma aba pra reordenar, sincroniza
        # `ws.runners` pra ordem dele virar a verdade — sem isso o
        # `_refresh_from_workspace` (chamado a cada add/remove) volta
        # pra ordem original e a sidebar fica fora de fase com o painel.
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)
        self._stack.addWidget(self.tabs)

        outer.addWidget(self._stack, stretch=1)

        # Callback definido por main_window para abrir o RunnerEditDialog
        # e/ou disparar a geração via IA. Mantém RunnerArea desacoplada
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

    def recent_output_for(self, runner_id: str, max_lines: int = 200) -> str:
        """Saída recente do widget do runner `runner_id`, se existir aba viva."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.runner_id() == runner_id:
                return w.recent_output(max_lines)
        return ""

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
        widget.url_changed.connect(
            lambda url, w=widget: self.runner_url_changed.emit(w.runner_id(), url)
        )
        widget.status_changed.connect(
            lambda txt, w=widget: self.runner_status_changed.emit(w.runner_id(), txt)
        )

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

    def _on_tab_moved(self, _from: int, _to: int) -> None:
        """Persiste a nova ordem das abas em `ws.runners` mantendo as
        posições relativas dos runners fora de escopo (eles não aparecem
        nas abas mas precisam ficar no mesmo lugar da lista). Emite
        `runners_changed` pra sidebar e o disco refletirem."""
        in_scope_ids: list[str] = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget):
                in_scope_ids.append(w.runner_id())
        by_id = {r.id: r for r in self._ws.runners}
        new_list: list[RunnerConfig] = []
        pos = 0
        for r in self._ws.runners:
            if self._matches_scope(r):
                if pos < len(in_scope_ids):
                    new_list.append(by_id[in_scope_ids[pos]])
                    pos += 1
            else:
                new_list.append(r)
        self._ws.runners = new_list
        self.runners_changed.emit()

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
        self.run_all()

    def _stop_all(self) -> None:
        self.stop_all()

    def run_all(self) -> None:
        """Inicia todos os runners habilitados deste escopo que não estão
        rodando. Público pra ser disparado de fora (ex.: header da sidebar)."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.config().enabled and not w.is_running():
                w.start()

    def stop_all(self) -> None:
        """Para todos os runners deste escopo que estão rodando."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RunnerWidget) and w.is_running():
                w.stop()

    def restart_all(self) -> None:
        """Reinicia todos os runners habilitados deste escopo. Quem está
        rodando faz `restart` (usa restart_cmd se houver); quem está parado
        é iniciado.

        Resync defensivo das abas antes de iterar: o header da sidebar pode
        ser clicado mesmo sem o painel de runners ter sido aberto, e nesse
        caso o RunnerArea pode estar fora de fase com `ws.runners` (runners
        adicionados via import/draft que não passaram por `_open_runner_edit`,
        por exemplo).
        """
        self._refresh_from_workspace()
        log = _logger()
        log.info(
            "restart_all: tabs=%d scope=%r",
            self.tabs.count(),
            self._console_session_id,
        )
        # NÃO respeita `enabled` — esse flag é só pro "▶ Rodar todos" do
        # painel de runners (escopo restrito). "Reiniciar todos" no header
        # da sidebar significa "reinicia geral, sem exceção" — incluir
        # disabled foi pedido explícito do usuário ao ver runner pulado.
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if not isinstance(w, RunnerWidget):
                continue
            if w.is_running():
                log.info("restart_all: restart %r", w.config().name)
                w.restart()
            else:
                log.info("restart_all: start %r", w.config().name)
                w.start()

    def _remove_all(self) -> None:
        in_scope = [r for r in self._ws.runners if self._matches_scope(r)]
        if not in_scope:
            QMessageBox.information(
                self,
                "Sem runners",
                "Não há runners para remover neste escopo.",
            )
            return
        scope_label = "deste console" if self._console_session_id else "do workspace"
        names = "\n".join(f"  • {r.name or '(sem nome)'}" for r in in_scope)
        if (
            QMessageBox.question(
                self,
                f"Remover todos os runners {scope_label}",
                f"Remover os {len(in_scope)} runners {scope_label}?\n\n"
                f"{names}\n\n"
                "Runners em execução serão parados. Runners de outros "
                "escopos NÃO são afetados.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        # Para apenas os runners que vão ser removidos (in_scope), nunca
        # toca em runners de outros escopos nem em terminais/consoles.
        ids_to_remove = {r.id for r in in_scope}
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if (
                isinstance(w, RunnerWidget)
                and w.runner_id() in ids_to_remove
                and w.is_running()
            ):
                w.stop()
        self._ws.runners = [r for r in self._ws.runners if r.id not in ids_to_remove]
        self.runners_changed.emit()
        self._refresh_from_workspace()

    def _open_more_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("✕ Remover todos", self._remove_all)
        menu.addSeparator()
        menu.addAction("Importar", self._import_runners)
        menu.addAction("Exportar", self._export_runners)
        if self._console_session_id:
            menu.addAction("↗ Copiar do workspace", self._open_copy_from_workspace_menu)
        menu.addAction("↻ Recarregar runners", self._reload_from_draft)
        menu.addSeparator()
        a_blank = menu.addAction("+ Novo runner em branco")
        a_blank.triggered.connect(lambda: self._edit_handler and self._edit_handler(None))
        a_gen = menu.addAction("Gerar com IA")
        a_gen.triggered.connect(lambda: self._generate_handler and self._generate_handler())
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

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
        from ..services.runner_gen_history import entries_for_workspace
        from ..services.runner_prompt import pending_runner_path

        path = pending_runner_path(self._ws)
        if not path.exists():
            QMessageBox.information(
                self,
                "Sem rascunho",
                f"Nenhum rascunho encontrado em:\n{path}\n\n"
                "Use '+ Novo → Gerar com IA' e aguarde o agente "
                "salvar o arquivo antes de recarregar.",
            )
            return
        # Carrega a entrada mais recente do histórico de runner-gen pra
        # stampar nos runners importados — assim o "Retomar geração" no
        # dialog de edição sabe qual sessão Claude abrir.
        recent = entries_for_workspace(self._ws.id)
        gen_sid = recent[0].session_id if recent else ""
        gen_cwd = recent[0].cwd if recent else ""
        try:
            added, replaced = import_runners(
                self._ws,
                path,
                console_session_id=self._console_session_id,
                gen_session_id=gen_sid,
                gen_cwd=gen_cwd,
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Erro ao importar rascunho", str(e))
            return
        self.runners_changed.emit()
        self._refresh_from_workspace()
        from .persistent_toast import flash_toast
        flash_toast(f"Rascunho importado — adicionados: {added}, substituídos: {replaced}")

    def _open_copy_from_workspace_menu(self) -> None:
        """Lista runners workspace-scoped num menu; clique copia pro console."""
        ws_runners = [
            r for r in self._ws.runners if not (r.console_session_id or "")
        ]
        menu = QMenu(self)
        if not ws_runners:
            act = menu.addAction("(nenhum runner no workspace)")
            act.setEnabled(False)
        else:
            all_act = menu.addAction("Copiar todos")
            all_act.triggered.connect(
                lambda: self._copy_runners_to_console(ws_runners)
            )
            menu.addSeparator()
            for r in ws_runners:
                label = r.name or "(sem nome)"
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _checked=False, src=r: self._copy_runners_to_console([src])
                )
        menu.exec(
            self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft())
        )

    def _copy_runners_to_console(self, sources: list[RunnerConfig]) -> None:
        if not sources or not self._console_session_id:
            return
        added = 0
        replaced = 0
        for src in sources:
            data = src.to_dict()
            data.pop("id", None)
            data["console_session_id"] = self._console_session_id
            clone = RunnerConfig.from_dict(data)
            # Substitui por nome dentro do mesmo escopo (consistente com
            # o merge do import_runners).
            existing_idx = next(
                (
                    i for i, r in enumerate(self._ws.runners)
                    if (r.console_session_id or "") == self._console_session_id
                    and r.name == clone.name
                ),
                -1,
            )
            if existing_idx >= 0:
                self._ws.runners[existing_idx] = clone
                replaced += 1
            else:
                self._ws.runners.append(clone)
                added += 1
        self.runners_changed.emit()
        self._refresh_from_workspace()
        from .persistent_toast import flash_toast
        flash_toast(f"Cópia concluída — adicionados: {added}, substituídos: {replaced}")

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
        from .persistent_toast import flash_toast
        flash_toast(f"Importação concluída — adicionados: {added}, substituídos: {replaced}")
