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

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import RunnerConfig
from ..pty_session import PtySession
from ..services.runner_url_detect import detect_url
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
        # URL atual conhecida pelo widget (config ou detectada). Mantida pra
        # sincronizar a sidebar (host:port). Inicializa a partir da config.
        self._current_url: str = (runner.browser_url or "").strip()
        # Buffer de log pra "Copiar log" — guarda os últimos ~1MB. Não
        # reseta a cada start (mantém histórico cross-restart pra debug).
        self._log_buf: str = ""
        self._log_buf_max: int = 1_000_000
        # Label curta da fase ("parado" no boot). Espelha em forma reduzida
        # o texto do _status; emitida via status_changed pra sidebar.
        self._status_label: str = "parado"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel("(parado)")
        self._status.setStyleSheet("color: #b0b0b0;")
        toolbar.addWidget(self._status)
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

        self._restart_btn = QPushButton("↻ Restart")
        self._restart_btn.clicked.connect(self.restart)
        toolbar.addWidget(self._restart_btn)

        self._edit_btn = QPushButton("⚙ Editar")
        self._edit_btn.clicked.connect(
            lambda: self.edit_requested.emit(self._runner.id)
        )
        toolbar.addWidget(self._edit_btn)

        self._copy_btn = QPushButton("📋 Copiar log")
        self._copy_btn.setToolTip("Copia o log atual deste runner pro clipboard")
        self._copy_btn.clicked.connect(self._copy_log)
        toolbar.addWidget(self._copy_btn)

        self._clear_btn = QPushButton("🧹 Limpar log")
        self._clear_btn.setToolTip(
            "Limpa o terminal e descarta o buffer de log deste runner"
        )
        self._clear_btn.clicked.connect(self._clear_log)
        toolbar.addWidget(self._clear_btn)

        # Altura igualada à dos botões irmãos — o glyph 🗑 sozinho
        # renderiza com line-height maior em algumas fontes e empurra o
        # botão pra cima dos demais. Width fixo mantém o look "icon-only".
        btn_h = self._copy_btn.sizeHint().height()
        self._del_btn = QPushButton("🗑")
        self._del_btn.setToolTip("Remover runner")
        self._del_btn.setFixedSize(36, btn_h)
        self._del_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._runner.id)
        )
        toolbar.addWidget(self._del_btn)

        outer.addLayout(toolbar)

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

    def update_config(self, runner: RunnerConfig) -> None:
        old_name = self._runner.name
        old_url = (self._runner.browser_url or "").strip()
        self._runner = runner
        if runner.name != old_name:
            self.config_label_changed.emit(runner.name or "(runner)")
        new_url = (runner.browser_url or "").strip()
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
        self.url_changed.emit(url)

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
        cwd = self._runner.cwd or self._default_cwd
        argv = ["bash", "-lc", cmd]
        # Reset do estado de detecção a cada start/restart pra reabrir
        # o browser numa nova execução.
        if intent in ("start", "restart"):
            self._output_buf = ""
            self._browser_opened_this_start = False
            self._ready_pattern_matched = False
        try:
            self.session.start(argv, cwd, env=self._runner.env or None)
        except OSError as e:
            log.exception("Falha ao iniciar runner")
            self._set_state("error", f"(erro) {e}")
            return
        # Para runners que abrem browser quando pronto: mostra "startando"
        # (transiente, amarelo na sidebar) até o ready_pattern/URL ser
        # detectado e o browser efetivamente abrir — aí vira "rodando" verde.
        if (
            intent in ("start", "restart")
            and self._runner.open_browser_on_ready
        ):
            label = "startando"
        else:
            label = {
                "start": "rodando", "stop": "parando", "restart": "reiniciando",
            }.get(intent, intent)
        self._set_state("running", f"● {label}: {cmd[:80]}", status_label=label)

    def _on_bridge_ready(self) -> None:
        self._bridge_ready = True
        if self._pending_cmd is not None:
            cmd, intent = self._pending_cmd
            self._pending_cmd = None
            self._spawn(cmd, intent)

    def _on_pty_output(self, data: bytes) -> None:
        try:
            chunk = data.decode("utf-8", errors="replace")
        except Exception:
            return
        # Log completo (cap em ~1MB) pra "Copiar log".
        self._log_buf = (self._log_buf + chunk)[-self._log_buf_max:]

        if not self._runner.open_browser_on_ready:
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

        url = self._runner.browser_url.strip() or detect_url(self._output_buf)
        if not url:
            return
        self._browser_opened_this_start = True
        self._set_current_url(url)
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
                argv = shlex.split(cmd) + [url]
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
