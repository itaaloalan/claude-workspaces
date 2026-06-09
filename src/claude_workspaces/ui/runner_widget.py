"""RunnerWidget — uma "aba" de runner com PTY + xterm.js.

Espelha TerminalWidget porém sem o parser de sessão Claude. Cada runner
tem botões próprios de Start/Stop/Restart/Editar/Remover e mostra o log
ao vivo no xterm.js (mesmo HTML/JS da aba Terminal).
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import RunnerConfig
from ..pty_session import PtySession
from ..services.runner_expand import (
    apply_port_arg,
    build_env,
    expand_port,
    expand_port_refs,
    wrap_with_node_bootstrap,
)
from ..services.runner_url_detect import detect_url, swap_url_port, url_port
from ..settings import Settings
from .terminal_widget import STATIC_DIR, TerminalBridge

log = logging.getLogger(__name__)


class RunnerWidget(QWidget):
    """Roda um RunnerConfig num PTY próprio, com toolbar e xterm.js."""

    # state ∈ {"idle", "running", "exited", "error"}
    state_changed = Signal(str)
    edit_requested = Signal(str)        # runner_id
    remove_requested = Signal(str)      # runner_id
    config_label_changed = Signal(str)  # novo nome p/ aba
    # URL atual (host:port) — detectada ou via config. "" quando desconhecida.
    # Emitido sempre que muda; consumido pela sidebar pra mostrar host:port
    # na linha do runner.
    url_changed = Signal(str)
    # Label curta da fase atual ("rodando"/"reiniciando"/"parando"/"parado"/
    # "erro"/"carregando"). Espelha o que aparece à esquerda do toolbar do
    # runner, em forma resumida pra ser exibido na sidebar.
    status_changed = Signal(str)
    # Cwd efetivo mudou (override do chip 📁, default do painel ou config).
    # Consumido pela sidebar pra refletir o 📁 sem abrir o painel.
    cwd_changed = Signal(str)
    # Porta base mudou via chip :porta — RunnerArea re-emite runners_changed
    # pro main_window persistir.
    port_changed = Signal(int)

    def __init__(
        self,
        runner: RunnerConfig,
        default_cwd: str,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._default_cwd = default_cwd
        self._settings = settings or Settings()
        self._intent: str = "start"   # último comando solicitado
        self._state: str = "idle"
        # Buffer recente da saída pra detecção de URL. Limitado pra não
        # crescer indefinidamente em runners de log alto.
        self._output_buf: str = ""
        self._browser_opened_this_start: bool = False
        self._ready_pattern_matched: bool = False
        self._rodando_emitted: bool = False
        # Aviso "porta configurada não aplicada" — uma vez por execução.
        self._port_mismatch_warned: bool = False
        # URL atual conhecida pelo widget (config ou detectada). Mantida pra
        # sincronizar a sidebar (host:port). Inicializa a partir da config
        # (com {port} já expandido pra porta do runner).
        self._current_url: str = expand_port(
            (runner.browser_url or "").strip(), runner.port
        )
        # Buffer de log pra "Copiar log" — guarda os últimos ~1MB. Não
        # reseta a cada start (mantém histórico cross-restart pra debug).
        self._log_buf: str = ""
        self._log_buf_max: int = 1_000_000
        # Label curta da fase ("parado" no boot). Espelha em forma reduzida
        # o texto do _status; emitida via status_changed pra sidebar.
        self._status_label: str = "parado"
        # Override de cwd escolhido pelo usuário no chip 📁 (ex.: apontar o
        # runner pro worktree de um console específico). Tem precedência
        # sobre runner.cwd/default. Persiste em runner.last_cwd — restart
        # do app mantém o último apontamento (se o diretório ainda existir;
        # worktree removido entre sessões cai de volta no padrão).
        self._cwd_override: str = ""
        if runner.last_cwd and Path(runner.last_cwd).is_dir():
            self._cwd_override = runner.last_cwd
        # Provider de diretórios dos consoles abertos do workspace —
        # lista de (label, path) injetada pela RunnerArea/main_window.
        self._console_dirs_provider = None
        # Provider nome→porta dos runners do MESMO escopo (placeholder
        # {port:<nome>} — ex: web referenciando a porta da api da stack).
        self._scope_ports_provider = None

        # A toolbar tem muitos botões (~8) em linha — a soma dos sizeHints
        # passa de 700px e propagaria mínimo de largura pra toda a hierarquia,
        # forçando scroll horizontal na janela ao abrir o painel de runners.
        # setMinimumWidth(0) quebra essa propagação no nível do widget raiz.
        self.setMinimumWidth(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar is a real QWidget so we can track hover and show/hide
        # secondary buttons (⚙, 📋, 🧹, 🗑) only when hovered.
        toolbar_widget = QWidget(self)
        toolbar_widget.setMinimumWidth(0)
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel("(parado)")
        self._status.setStyleSheet("color: #b0b0b0;")
        # Status pode ser longo; Ignored evita que empurre o mínimo horizontal.
        self._status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._status.setMinimumWidth(0)
        toolbar.addWidget(self._status)

        # Chip 📁 com o cwd EFETIVO do runner — com vários consoles (cada um
        # podendo estar num worktree), mostra pra onde o runner aponta e
        # permite redirecioná-lo pro diretório de um console específico.
        self._cwd_btn = QPushButton()
        self._cwd_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9aa0a6; "
            "border: 1px solid #2c2c2c; border-radius: 9px; "
            "padding: 1px 8px; font-size: 11px; }"
            "QPushButton:hover { color: #e6e6e6; border-color: #3d6ea8; }"
        )
        self._cwd_btn.clicked.connect(self._open_cwd_menu)
        toolbar.addWidget(self._cwd_btn)
        self._refresh_cwd_chip()

        # Chip :porta — porta base do runner, sempre visível (mesmo sem
        # porta) pra ser descoberto. Clique abre o editor rápido; o campo
        # também existe no dialog ⚙ Editar.
        self._port_btn = QPushButton()
        self._port_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9aa0a6; "
            "border: 1px solid #2c2c2c; border-radius: 9px; "
            "padding: 1px 8px; font-size: 11px; }"
            "QPushButton:hover { color: #e6e6e6; border-color: #3d8a5f; }"
        )
        self._port_btn.setToolTip(
            "Porta base do runner — clique pra alterar. {port} no "
            "Start/Stop/Restart, na URL do browser e nos valores do env é "
            "substituído por ela ao rodar, e PORT=<porta> é injetada no "
            "ambiente (a menos que você defina PORT no env). Cópias pra "
            "consoles/worktrees ganham a próxima porta livre. 0 = sem porta."
        )
        self._port_btn.clicked.connect(self._open_port_dialog)
        toolbar.addWidget(self._port_btn)
        self._refresh_port_chip()

        # Chip 🌐 — URL do runner (config ou detectada na stdout), clicável
        # pra abrir no navegador. Oculto enquanto não há URL.
        self._url_btn = QPushButton()
        self._url_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #9aa0a6; "
            "border: 1px solid #2c2c2c; border-radius: 9px; "
            "padding: 1px 8px; font-size: 11px; }"
            "QPushButton:hover { color: #e6e6e6; border-color: #3d6ea8; }"
        )
        self._url_btn.clicked.connect(
            lambda _c=False: self._current_url
            and self._open_browser(self._current_url)
        )
        self._url_btn.setVisible(False)
        toolbar.addWidget(self._url_btn)
        self._refresh_url_chip()
        toolbar.addStretch()

        # Filtro de log — substring case-insensitive aplicada linha a linha.
        # Mudanças disparam replay do buffer pra refletir o filtro no
        # histórico já recebido, não só nas linhas futuras.
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filtrar logs…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setFixedWidth(180)
        self._filter_edit.setToolTip(
            "Mostra só linhas que contêm o texto (case-insensitive). "
            "Esvazie pra ver o log completo."
        )
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_edit)

        self._start_btn = QPushButton("▶ Start")
        self._start_btn.clicked.connect(self.start)
        toolbar.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop)
        toolbar.addWidget(self._stop_btn)

        self._clear_log_btn = QPushButton("🧹 Limpar logs")
        self._clear_log_btn.clicked.connect(self._clear_log)
        toolbar.addWidget(self._clear_log_btn)

        self._more_btn = QPushButton("⋯")
        self._more_btn.setFixedWidth(32)
        self._more_btn.setToolTip("Mais ações")
        self._more_btn.clicked.connect(self._open_more_menu)
        toolbar.addWidget(self._more_btn)

        outer.addWidget(toolbar_widget)

        self.session = PtySession(self)
        self.session.finished.connect(self._on_session_finished)
        self.session.output_received.connect(self._on_pty_output)

        self.bridge = TerminalBridge(self.session)
        self.bridge.ready.connect(self._on_bridge_ready)

        self.view = QWebEngineView(self)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        html_path = STATIC_DIR / "terminal.html"
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))
        outer.addWidget(self.view, stretch=1)

        self._bridge_ready = False
        self._pending_cmd: tuple[str, str] | None = None  # (cmd, intent)

    # ---- toolbar menu ----------------------------------------------------

    def _open_more_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("⚙ Editar", lambda: self.edit_requested.emit(self._runner.id))
        menu.addAction("📋 Copiar log", self._copy_log)
        menu.addAction("🧹 Limpar log", self._clear_log)
        menu.addSeparator()
        menu.addAction("🗑 Remover runner", lambda: self.remove_requested.emit(self._runner.id))
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

    # ---- config ----------------------------------------------------------

    def runner_id(self) -> str:
        return self._runner.id

    def config(self) -> RunnerConfig:
        return self._runner

    def recent_output(self, max_lines: int = 200) -> str:
        """Últimas linhas do log (ANSI removido) pra dar contexto ao Claude.

        Usado pelo "Editar com Claude" — passa o erro/saída recente do
        runner pro Claude diagnosticar (ex: 'invalid target release: 25').
        Vazio se o runner nunca rodou.
        """
        from ..services.runner_url_detect import strip_ansi

        if not self._log_buf:
            return ""
        text = strip_ansi(self._log_buf)
        lines = text.splitlines()
        return "\n".join(lines[-max_lines:])

    def set_default_cwd(self, cwd: str) -> None:
        """Atualiza o cwd padrão usado quando `runner.cwd` está vazio.
        Usado pelo painel de console pra apontar ao worktree do console."""
        before = self.effective_cwd()
        self._default_cwd = cwd
        self._refresh_cwd_chip()
        if self.effective_cwd() != before:
            self.cwd_changed.emit(self.effective_cwd())

    def set_scope_ports_provider(self, fn) -> None:
        """Callable() -> dict[nome, porta] dos runners do mesmo escopo —
        resolve o placeholder {port:<nome>} em comandos/env/browser_url."""
        self._scope_ports_provider = fn

    def _scope_ports(self) -> dict[str, int]:
        if self._scope_ports_provider is None:
            return {}
        try:
            return dict(self._scope_ports_provider() or {})
        except Exception:
            log.debug("scope_ports_provider falhou", exc_info=True)
            return {}

    def set_console_dirs_provider(self, fn) -> None:
        """Callable() -> list[(label, path)] com os diretórios dos consoles
        abertos do workspace (worktree quando houver). Alimenta o menu do
        chip 📁 pra apontar o runner pro diretório de um console."""
        self._console_dirs_provider = fn

    def effective_cwd(self) -> str:
        """Cwd em que o próximo start vai rodar: override do usuário (chip
        📁) > cwd da config do runner > default do painel."""
        return self._cwd_override or self._runner.cwd or self._default_cwd

    def _refresh_cwd_chip(self) -> None:
        from pathlib import Path
        cwd = self.effective_cwd()
        name = Path(cwd).name if cwd else "?"
        if self._cwd_override:
            source = "apontado manualmente (chip 📁)"
        elif self._runner.cwd:
            source = "cwd da config do runner"
        else:
            source = "pasta padrão do painel"
        self._cwd_btn.setText(f"📁 {name}")
        self._cwd_btn.setToolTip(
            f"Diretório do runner: {cwd or '(indefinido)'}\n"
            f"Origem: {source}\n"
            "Clique pra apontar pro diretório de um console "
            "(aplica no próximo start/restart)."
        )

    def _refresh_port_chip(self) -> None:
        port = self._runner.port
        if port > 0:
            self._port_btn.setText(f":{port}")
        else:
            self._port_btn.setText(":porta")

    def _open_port_dialog(self) -> None:
        value, ok = QInputDialog.getInt(
            self,
            "Porta base",
            "Porta base do runner (0 = sem porta).\n"
            "Use {port} nos comandos/URL/env; PORT=<porta> é injetada "
            "no ambiente.",
            value=self._runner.port,
            minValue=0,
            maxValue=65535,
        )
        if not ok or value == self._runner.port:
            return
        self._runner.port = value
        self._refresh_port_chip()
        # browser_url com {port} → re-sincroniza a URL da sidebar.
        if self._runner.browser_url.strip():
            self._set_current_url(self._effective_browser_url())
        if self._state == "running":
            self._status.setText("● porta alterada — reinicie o runner pra aplicar")
        self.port_changed.emit(value)

    def _open_cwd_menu(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        current = self.effective_cwd()

        def add_option(label: str, path: str, override: str) -> None:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(bool(path) and path == current)
            act.triggered.connect(
                lambda _=False, o=override: self.set_cwd_override(o)
            )

        base = self._runner.cwd or self._default_cwd
        base_name = Path(base).name if base else "?"
        add_option(f"Padrão — {base_name}  ({base})", base, "")
        dirs: list[tuple[str, str]] = []
        if self._console_dirs_provider is not None:
            try:
                dirs = list(self._console_dirs_provider() or [])
            except Exception:
                log.debug("console_dirs_provider falhou", exc_info=True)
        if dirs:
            menu.addSeparator()
            sec = menu.addAction("Consoles abertos")
            sec.setEnabled(False)
            for label, path in dirs:
                if not path or path == base:
                    continue
                add_option(f"{label}  ({path})", path, path)
        menu.exec(self._cwd_btn.mapToGlobal(self._cwd_btn.rect().bottomLeft()))

    def set_cwd_override(self, path: str) -> None:
        """Aponta o runner pra `path` ("" volta ao padrão). Também usado
        pela sidebar — emite cwd_changed pra UI refletir. Grava em
        runner.last_cwd (objeto compartilhado com ws.runners); quem persiste
        o workspace é o main_window no handler de cwd_changed."""
        if path == self._cwd_override:
            return
        self._cwd_override = path
        self._runner.last_cwd = path
        self._refresh_cwd_chip()
        if self._state == "running":
            self._status.setText(
                "● cwd alterado — reinicie o runner pra aplicar"
            )
        self.cwd_changed.emit(self.effective_cwd())

    def _effective_browser_url(self) -> str:
        """browser_url da config com {port} (e {port:<nome>}) expandidos."""
        url = expand_port(
            (self._runner.browser_url or "").strip(), self._runner.port
        )
        return expand_port_refs(url, self._scope_ports())

    def update_config(self, runner: RunnerConfig) -> None:
        old_name = self._runner.name
        old_url = self._effective_browser_url()
        before_cwd = self.effective_cwd()
        self._runner = runner
        # O dialog de edição pode entregar um RunnerConfig sem o last_cwd —
        # re-aplica o apontamento ativo pra não perder a persistência.
        if self._cwd_override:
            self._runner.last_cwd = self._cwd_override
        self._refresh_cwd_chip()
        self._refresh_port_chip()
        if self.effective_cwd() != before_cwd:
            self.cwd_changed.emit(self.effective_cwd())
        if runner.name != old_name:
            self.config_label_changed.emit(runner.name or "(runner)")
        new_url = self._effective_browser_url()
        # browser_url da config tem prioridade sobre URL detectada — se
        # mudou, sincroniza a sidebar; se ficou vazio e tínhamos detectado
        # algo, mantém o detectado.
        if new_url and new_url != old_url:
            self._set_current_url(new_url)
        elif not new_url and old_url and self._current_url == old_url:
            self._set_current_url("")

    def current_url(self) -> str:
        return self._current_url

    def _set_current_url(self, url: str) -> None:
        url = (url or "").strip()
        if url == self._current_url:
            return
        self._current_url = url
        self._refresh_url_chip()
        self.url_changed.emit(url)

    def _refresh_url_chip(self) -> None:
        url = self._current_url
        if not url:
            self._url_btn.setVisible(False)
            return
        from .runner_child_widget import _host_port
        addr = _host_port(url) or url
        self._url_btn.setText(f"🌐 {addr}")
        self._url_btn.setToolTip(f"Abrir {url} no navegador")
        self._url_btn.setVisible(True)

    def _warn_port_mismatch(self, url: str) -> None:
        """URL real detectada com porta ≠ da configurada → o comando não
        aplicou a porta alocada (ex: ng serve com --port hardcoded; servidor
        que não lê PORT/SERVER_PORT). Avisa uma vez por execução no log do
        runner + status, com a correção sugerida."""
        if self._port_mismatch_warned or self._runner.port <= 0:
            return
        m = re.search(r":(\d{2,5})(?:[/\s]|$)", url)
        if not m:
            return
        real = int(m.group(1))
        if real == self._runner.port:
            return
        self._port_mismatch_warned = True
        cfg = self._runner.port
        msg = (
            f"\r\n\x1b[38;5;214m⚠ rodando na :{real} — a porta configurada "
            f":{cfg} não foi aplicada pelo comando.\r\n"
            "  Use {port} no start_cmd (ex: npm start -- --port {port} / "
            "--server.port={port}) ou deixe o servidor ler a env "
            "PORT/SERVER_PORT.\x1b[0m\r\n"
        )
        self._log_buf = (self._log_buf + msg)[-self._log_buf_max:]
        try:
            self.bridge.output_to_terminal.emit(msg.encode("utf-8"))
        except Exception:
            log.debug("emit do aviso de porta falhou", exc_info=True)
        self._status.setText(f"● rodando na :{real} (≠ :{cfg} configurada)")
        self._port_btn.setToolTip(
            f"⚠ Configurada :{cfg}, mas o processo subiu na :{real} — o "
            "comando não usa {port} e o servidor não leu PORT/SERVER_PORT. "
            "Clique pra alterar a porta base."
        )

    def is_running(self) -> bool:
        return self._state == "running"

    def current_status_label(self) -> str:
        return self._status_label

    def _emit_status_label(self, label: str) -> None:
        if label != self._status_label:
            self._status_label = label
            self.status_changed.emit(label)

    def current_state(self) -> str:
        return self._state

    # ---- intents ---------------------------------------------------------

    def start(self) -> None:
        cmd = (self._runner.start_cmd or "").strip()
        if not cmd:
            self._set_state("error", "(start_cmd vazio)")
            return
        self._intent = "start"
        self._spawn(cmd, "start")

    def stop(self) -> None:
        # Com stop_cmd: roda como comando substituto no mesmo PTY (o start
        # process será terminado automaticamente pelo PtySession.start).
        # Sem stop_cmd: apenas mata o PTY atual (SIGHUP).
        cmd = (self._runner.stop_cmd or "").strip()
        self._intent = "stop"
        if cmd:
            self._spawn(cmd, "stop")
        else:
            if self.session.is_running():
                self.session.terminate()
            # _on_session_finished cuidará da transição de estado.

    def restart(self) -> None:
        cmd = (self._runner.restart_cmd or "").strip()
        self._intent = "restart"
        if cmd:
            self._spawn(cmd, "restart")
        else:
            # Sem restart_cmd: stop seguido de start.
            was_running = self.session.is_running()
            if was_running:
                self.session.terminate()
            self.start()

    def terminate(self) -> None:
        """Mata o PTY sem rodar stop_cmd — usado no shutdown da aplicação."""
        if self.session.is_running():
            self.session.terminate()

    # ---- core ------------------------------------------------------------

    def _spawn(self, cmd: str, intent: str) -> None:
        # Não bloqueia por bridge: o PTY roda independente do display do
        # xterm.js. Output que chegar antes do bridge JS subscrever fica
        # só no `_log_buf` (acessível via "Copiar log"). Sem isso, clicar
        # "Reiniciar todos" no header da sidebar com o RunnerArea ainda
        # não realizado deixava os processos parados — o widget enfileirava
        # `_pending_cmd` esperando um bridge que demorava demais a ficar
        # ready em painel ainda não visível.
        # Apontamento pra diretório que sumiu (worktree removido com o app
        # aberto) → volta ao padrão antes de resolver, evitando start num
        # cwd inexistente. set_cwd_override re-sincroniza chip/sidebar.
        if self._cwd_override and not Path(self._cwd_override).is_dir():
            self.set_cwd_override("")
        cwd = self.effective_cwd()
        # {port} → porta do runner (start/stop/restart_cmd passam todos por
        # aqui). Persistido fica o literal; a expansão é só na execução.
        had_placeholder = "{port}" in cmd
        cmd = expand_port(cmd, self._runner.port)
        # {port:<nome>} → porta de outro runner do mesmo escopo (ex: web
        # apontando pra api da mesma stack/console).
        scope_ports = self._scope_ports()
        cmd = expand_port_refs(cmd, scope_ports)
        # "Inteligência" de porta: comando sem {port} mas com porta
        # configurada → anexa a flag em dev servers conhecidos (a última
        # --port vence no ng/vite, sobrepondo hardcoded do package.json).
        port_auto_applied = False
        if (
            intent in ("start", "restart")
            and self._runner.port > 0
            and not had_placeholder
        ):
            applied = apply_port_arg(cmd, self._runner.port)
            if applied:
                cmd = applied
                port_auto_applied = True
        # Texto exibido no status — sem o prefixo de bootstrap abaixo.
        display_cmd = cmd
        # Worktree recém-criado não tem node_modules — instala deps antes
        # do start quando há package.json sem node_modules (no-op senão).
        if intent in ("start", "restart"):
            cmd = wrap_with_node_bootstrap(cmd)
        argv = ["bash", "-lc", cmd]
        # Reset do estado de detecção a cada start/restart pra reabrir
        # o browser numa nova execução.
        if intent in ("start", "restart"):
            self._output_buf = ""
            self._browser_opened_this_start = False
            self._ready_pattern_matched = False
            self._rodando_emitted = False
            self._port_mismatch_warned = False
            # Banner com o diretório/worktree no INÍCIO de cada execução —
            # com vários consoles/worktrees, deixa explícito onde o runner
            # está rodando sem precisar abrir o chip 📁.
            self._emit_cwd_banner(cwd, port_auto_applied=port_auto_applied)
        try:
            # Intents "stop"/"restart" só chegam aqui quando o runner tem
            # stop_cmd/restart_cmd — comandos substitutos que gerenciam o
            # serviço de fundo eles mesmos. Nesses casos o PTY anterior
            # (tipicamente `exec tail -F`) morre sozinho (kill no pid, não
            # killpg): matar o grupo derrubava o DAS do GlassFish antes do
            # `asadmin redeploy` do restart_cmd rodar.
            # build_env: expande {port} nos valores e injeta PORT/SERVER_PORT
            # quando o runner tem porta (sem sobrescrever explícitos);
            # {port:<nome>} resolve pros vizinhos do escopo.
            env = build_env(self._runner.env or {}, self._runner.port)
            if scope_ports:
                env = {
                    k: expand_port_refs(v, scope_ports)
                    for k, v in env.items()
                }
            self.session.start(
                argv,
                cwd,
                env=env or None,
                kill_group_on_replace=(intent == "start"),
            )
        except OSError as e:
            log.exception("Falha ao iniciar runner")
            self._set_state("error", f"(erro) {e}")
            return
        # Para runners que abrem browser quando pronto: mostra "startando"
        # (transiente, amarelo na sidebar) até o ready_pattern/URL ser
        # detectado e o browser efetivamente abrir — aí vira "rodando" verde.
        if intent in ("start", "restart"):
            label = "startando"
        else:
            label = {"stop": "parando"}.get(intent, intent)
        self._set_state(
            "running", f"● {label}: {display_cmd[:80]}", status_label=label
        )

    def _on_bridge_ready(self) -> None:
        self._bridge_ready = True
        # Destrava o repasse ao vivo do PTY pro xterm. O gate `_live` do
        # TerminalBridge nasce desligado (lazy-load do console, 1.0.3) e quem
        # o liga é o go_live() — mas só o TerminalWidget chamava. O runner
        # tem view eager e precisava destravar aqui; sem isto, `_on_pty_output`
        # do bridge descartava todo output ao vivo e só os emits diretos
        # (banner/avisos) apareciam — o log do processo sumia. Replaya o que
        # já foi bufferizado em `_log_buf` antes do frontend carregar.
        try:
            self.bridge.go_live(self._log_buf.encode("utf-8", errors="replace"))
        except Exception:
            log.debug("go_live do runner falhou", exc_info=True)
        if self._pending_cmd is not None:
            cmd, intent = self._pending_cmd
            self._pending_cmd = None
            self._spawn(cmd, intent)

    def _emit_cwd_banner(
        self, cwd: str, port_auto_applied: bool = False
    ) -> None:
        """Escreve no terminal do runner (e no log) uma linha com o
        diretório em que esta execução vai rodar — e a branch 🌿 quando o
        diretório é um git worktree linkado."""
        suffix = ""
        try:
            from ..git_worktree import current_branch, is_worktree_path
            if cwd and is_worktree_path(cwd):
                br = current_branch(cwd)
                suffix = f" \x1b[38;5;78m🌿 {br or 'worktree'}\x1b[0m"
        except Exception:
            log.debug("detecção de worktree pro banner falhou", exc_info=True)
        if self._runner.port > 0:
            suffix += f" \x1b[38;5;180m:{self._runner.port}\x1b[0m"
        extra = ""
        if port_auto_applied:
            extra = (
                f"\x1b[38;5;114m🔌 porta :{self._runner.port} aplicada "
                "automaticamente ao comando\x1b[0m\r\n"
            )
        banner = (
            f"\r\n\x1b[38;5;110m📁 rodando em: {cwd or '(indefinido)'}"
            f"\x1b[0m{suffix}\r\n{extra}\r\n"
        )
        self._log_buf = (self._log_buf + banner)[-self._log_buf_max:]
        try:
            self.bridge.output_to_terminal.emit(banner.encode("utf-8"))
        except Exception:
            log.debug("emit do banner de cwd falhou", exc_info=True)

    def _on_pty_output(self, data: bytes) -> None:
        try:
            chunk = data.decode("utf-8", errors="replace")
        except Exception:
            return
        # Log completo (cap em ~1MB) pra "Copiar log".
        self._log_buf = (self._log_buf + chunk)[-self._log_buf_max:]

        if not self._runner.open_browser_on_ready:
            if self._intent in ("start", "restart"):
                self._output_buf = (self._output_buf + chunk)[-16384:]
                if not self._rodando_emitted:
                    ready_pat = (self._runner.ready_pattern or "").strip()
                    if ready_pat:
                        try:
                            matched = bool(re.search(ready_pat, self._output_buf, re.IGNORECASE))
                        except re.error:
                            matched = True
                        if matched:
                            self._rodando_emitted = True
                            self._emit_status_label("rodando")
                    else:
                        self._rodando_emitted = True
                        self._emit_status_label("rodando")
                # Detecção de URL mesmo sem abrir browser — alimenta o
                # chip 🌐, a sidebar e o aviso de porta não aplicada.
                if not self._current_url:
                    url = detect_url(self._output_buf)
                    if url:
                        self._set_current_url(url)
                        self._warn_port_mismatch(url)
            return
        if self._browser_opened_this_start:
            return
        if self._intent != "start" and self._intent != "restart":
            return
        # Mantém só os últimos ~16KB pra detecção (URLs aparecem cedo
        # no startup, mas alguns servers logam warnings antes).
        self._output_buf = (self._output_buf + chunk)[-16384:]

        ready_pat = (self._runner.ready_pattern or "").strip()
        if ready_pat and not self._ready_pattern_matched:
            try:
                if re.search(ready_pat, self._output_buf, re.IGNORECASE):
                    self._ready_pattern_matched = True
            except re.error as e:
                log.warning(
                    "ready_pattern inválido no runner %s: %s — ignorando",
                    self._runner.name, e,
                )
                self._ready_pattern_matched = True
            if not self._ready_pattern_matched:
                return

        cfg = self._effective_browser_url()
        detected = detect_url(self._output_buf)
        url = cfg or detected
        if not url:
            return
        # Config carrega o PATH certo mas pode ter porta hardcoded — a
        # porta REAL entra no lugar: detectada no log (verdade absoluta)
        # > alocada no runner > config como está.
        if cfg:
            real = url_port(detected or "") or (
                self._runner.port if self._runner.port > 0 else 0
            )
            if real:
                url = swap_url_port(cfg, real)
        self._browser_opened_this_start = True
        self._set_current_url(url)
        # Aviso de descompasso compara a porta REAL (detectada) — a url
        # acima pode já ter sido corrigida pro swap e mascararia o caso.
        self._warn_port_mismatch(detected or url)
        # Sai do label "startando" → "rodando" agora que detectamos o
        # ready/URL e vamos abrir o browser. State continua "running".
        self._emit_status_label("rodando")
        # Delay configurável (default 5s) — dá tempo do server aceitar
        # conexões antes do browser bater na porta. Glassfish/Spring Boot
        # logam a URL antes do listener tá pronto.
        delay_ms = max(0, int(getattr(self._settings, "browser_open_delay_ms", 5000)))
        QTimer.singleShot(delay_ms, lambda u=url: self._open_browser(u))

    def _copy_log(self) -> None:
        from PySide6.QtGui import QGuiApplication

        from ..services.runner_url_detect import strip_ansi

        text = strip_ansi(self._log_buf) if self._log_buf else ""
        QGuiApplication.clipboard().setText(text)
        prev = self._status.text()
        self._status.setText(
            f"(log copiado — {len(text)} chars)"
            if text
            else "(log vazio)"
        )
        # Volta o status original depois de 2s.
        QTimer.singleShot(2000, lambda t=prev: self._status.setText(t))

    def _on_filter_changed(self, text: str) -> None:
        self.bridge.set_filter(text)
        self.bridge.replay_filtered(self._log_buf)

    def _clear_log(self) -> None:
        self._log_buf = ""
        self._output_buf = ""
        self.bridge.clear_requested.emit()
        prev = self._status.text()
        self._status.setText("(log limpo)")
        QTimer.singleShot(2000, lambda t=prev: self._status.setText(t))

    def _open_browser(self, url: str) -> None:
        cmd = (self._settings.browser_command or "").strip()
        log.info("Abrindo browser para runner %s: %s", self._runner.name, url)
        if cmd:
            try:
                argv = self._browser_argv(cmd, url)
                subprocess.Popen(  # noqa: S603
                    argv,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except (OSError, ValueError) as e:
                log.warning("browser_command falhou (%s), caindo em xdg-open", e)
        QDesktopServices.openUrl(QUrl(url))

    def _browser_argv(self, cmd: str, url: str) -> list[str]:
        argv = shlex.split(cmd)
        if not argv:
            return [url]
        exe = Path(argv[0]).name.lower()
        known_tab_browsers = (
            "firefox",
            "firefox-bin",
            "google-chrome",
            "chrome",
            "chromium",
            "chromium-browser",
            "brave",
            "brave-browser",
            "microsoft-edge",
            "microsoft-edge-stable",
        )
        if exe in known_tab_browsers and not any(
            arg in {"--new-tab", "--new-window"} for arg in argv[1:]
        ):
            return [*argv, "--new-tab", url]
        return [*argv, url]

    def _on_session_finished(self) -> None:
        # Quando o processo termina, o estado depende do que estava rodando:
        # - intent=start ou restart → o processo morreu/terminou → "exited"
        # - intent=stop → bem-sucedido → "exited"
        # (não tem como sair de stop pra running sem nova chamada explícita)
        self._set_state("exited", "(processo encerrado)")

    def _set_state(
        self, state: str, status_text: str, status_label: str | None = None
    ) -> None:
        prev = self._state
        self._state = state
        self._status.setText(status_text)
        running = state == "running"
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        if status_label is None:
            status_label = {
                "error": "erro",
                "exited": "parado",
                "idle": "parado",
                "running": "rodando",
            }.get(state, state)
        # Ordem importa: state primeiro (sidebar re-aplica o label padrão
        # via _apply_state), status depois (pode sobrescrever com label
        # transiente tipo "startando"/"reiniciando").
        if prev != state:
            self.state_changed.emit(state)
        self._emit_status_label(status_label)

    def closeEvent(self, event) -> None:  # noqa: D401
        self.terminate()
        super().closeEvent(event)
