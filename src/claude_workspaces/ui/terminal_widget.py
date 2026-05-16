import logging
import os
import pwd
import shlex
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..pty_session import PtySession


def _login_shell() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        return os.environ.get("SHELL", "/bin/bash")


log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class TerminalBridge(QObject):
    # QByteArray vira ArrayBuffer no JS, deixando o xterm.js decodificar
    # UTF-8 corretamente (chars multi-byte como ─ │ ╭ não quebram).
    output_to_terminal = Signal("QByteArray")
    force_fit_requested = Signal()
    ready = Signal()

    def __init__(self, session: PtySession) -> None:
        super().__init__()
        self.session = session
        self.session.output_received.connect(self._on_pty_output)

    def _on_pty_output(self, data: bytes) -> None:
        self.output_to_terminal.emit(data)

    @Slot(str)
    def input_from_terminal(self, data: str) -> None:
        self.session.write(data.encode("utf-8"))

    @Slot(int, int)
    def resize_terminal(self, cols: int, rows: int) -> None:
        self.session.resize(cols, rows)

    @Slot()
    def frontend_ready(self) -> None:
        self.ready.emit()


class TerminalWidget(QWidget):
    running_changed = Signal(bool)
    activity_changed = Signal(str, bool)  # status_text, is_working

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_running = False
        self._output_buffer = bytearray()
        self._last_output_time = 0.0
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(250)
        self._activity_timer.timeout.connect(self._poll_activity)
        self._last_status = ""
        self._last_working = False
        self._activity_dirty = False
        # Context Claude (cwd + resume) pra descobrir o título da sessão
        # via scan do ~/.claude/projects/<cwd>/*.jsonl
        self._claude_cwd: str | None = None
        self._claude_resume_id: str | None = None
        self._claude_start_time: float = 0.0
        self._session_preview: str | None = None
        self._session_resolved: bool = False
        # Debounce do refit do xterm.js — durante drag de splitter / resize
        # de janela, evita disparar fits em rajada (cada um dispara 6 fits
        # com timeouts internos no JS → CPU thrash)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(120)
        self._fit_timer.timeout.connect(self._emit_force_fit)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel("(terminal vazio)")
        self._status.setStyleSheet("color: #b0b0b0;")
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        self._stop_btn = QPushButton("Encerrar")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.terminate)
        toolbar.addWidget(self._stop_btn)
        outer.addLayout(toolbar)

        self.session = PtySession(self)
        self.session.finished.connect(self._on_session_finished)
        self.session.output_received.connect(self._record_output)

        self.bridge = TerminalBridge(self.session)
        self.bridge.ready.connect(self._on_bridge_ready)

        self.view = QWebEngineView(self)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        html_path = STATIC_DIR / "terminal.html"
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))

        outer.addWidget(self.view, stretch=1)

        self._pending: tuple[list[str], str, str | None] | None = None
        self._bridge_ready = False

        # Callback "Claude pronto pra receber input" — usado pelo handoff
        # pra evitar QTimer de 4s fixo. Disparado uma vez quando aparece
        # idle marker no buffer (ou fallback por timeout).
        self._ready_callback: Callable[[bool], None] | None = None
        self._ready_timeout: QTimer | None = None

    def _on_bridge_ready(self) -> None:
        log.info("Terminal bridge pronto")
        self._bridge_ready = True
        if self._pending is not None:
            argv, cwd, label = self._pending
            self._pending = None
            self._start_now(argv, cwd, label)

    def _set_running(self, running: bool) -> None:
        if self._is_running != running:
            self._is_running = running
            self.running_changed.emit(running)
            if running:
                self._activity_timer.start()
            else:
                self._activity_timer.stop()
                # Emite estado final "idle" pra UI limpar o spinner
                self.activity_changed.emit("(encerrado)", False)

    def is_running(self) -> bool:
        return self._is_running

    def configure_claude(self, cwd: str, resume_id: str | None = None) -> None:
        """Diz à TerminalWidget que o comando rodando é um Claude — assim
        ela consegue resolver o título da sessão (primeiro user prompt)
        olhando os JSONLs em ~/.claude/projects/<encoded-cwd>/."""
        self._claude_cwd = cwd
        self._claude_resume_id = resume_id
        # time.time() (wall clock) pra comparar com os.path.getmtime; NÃO
        # use monotonic aqui — referências diferentes, comparação errada
        # acabaria casando sessões antigas e mostrando título reciclado
        self._claude_start_time = time.time()
        self._session_preview = None
        self._session_resolved = False

    def effective_title(self) -> str:
        """Título preferido — preview da sessão (truncado) ou _base_title."""
        if self._session_preview:
            text = self._session_preview.replace("\n", " ").strip()
            if len(text) > 60:
                text = text[:59] + "…"
            return text
        return self.property("_base_title") or ""

    def full_title(self) -> str:
        if self._session_preview:
            return self._session_preview.strip()
        return self.property("_base_title") or ""

    def _try_resolve_session(self) -> None:
        if self._session_resolved or not self._claude_cwd:
            return
        try:
            from ..claude_sessions import list_sessions
            sessions = list_sessions(self._claude_cwd, limit=8)
        except Exception:
            log.debug("session resolution falhou em %s", self._claude_cwd, exc_info=True)
            return
        if not sessions:
            return
        if self._claude_resume_id:
            for s in sessions:
                if s.id == self._claude_resume_id:
                    self._session_preview = s.preview or ""
                    self._session_resolved = True
                    return
            return
        # Sessão nova — pega a mais recente criada após nosso start
        # (-5s pra tolerar drift). Se nada bater ainda, tenta no próximo tick.
        matching = [s for s in sessions if s.mtime >= self._claude_start_time - 5]
        if not matching:
            return
        matching.sort(key=lambda s: s.mtime, reverse=True)
        preview = matching[0].preview or ""
        if preview:
            self._session_preview = preview
            self._session_resolved = True

    def _record_output(self, data: bytes) -> None:
        self._output_buffer.extend(data)
        if len(self._output_buffer) > 8192:
            del self._output_buffer[:-8192]
        self._last_output_time = time.monotonic()
        self._activity_dirty = True

    def _poll_activity(self) -> None:
        from ..claude_activity import has_idle_marker, parse_status
        age = (
            time.monotonic() - self._last_output_time
            if self._last_output_time
            else 999.0
        )
        # Tenta resolver o título da sessão (Claude grava JSONL ~1-3s após start)
        self._try_resolve_session()
        # Verifica callback de "pronto" independente do dirty check —
        # depende do buffer corrente, não do diff de status
        if self._ready_callback is not None and has_idle_marker(
            bytes(self._output_buffer)
        ):
            self._fire_ready_callback(True)
        if not self._activity_dirty and self._last_working and age <= 2.5:
            return
        self._activity_dirty = False
        activity = parse_status(bytes(self._output_buffer), age)
        if (
            activity.status != self._last_status
            or activity.is_working != self._last_working
        ):
            self._last_status = activity.status
            self._last_working = activity.is_working
            self.activity_changed.emit(activity.status, activity.is_working)

    def when_claude_ready(
        self,
        callback: Callable[[bool], None],
        timeout_ms: int = 30000,
    ) -> None:
        """Chama `callback(success)` uma vez quando detectar que o Claude
        está pronto pra receber input (idle marker no buffer). Se não
        detectar até `timeout_ms`, chama com success=False.

        Substitui o `QTimer.singleShot(4000)` do handoff, que era frágil
        (Claude pode demorar mais que 4s pra subir em máquina lenta)."""
        from ..claude_activity import has_idle_marker

        if not self._is_running:
            callback(False)
            return
        # Já pronto agora — dispara no próximo tick pra não confundir caller
        if has_idle_marker(bytes(self._output_buffer)):
            QTimer.singleShot(0, lambda: callback(True))
            return
        # Já tem um callback pendente — descarta o anterior (rare race, mas
        # melhor não silently combinar)
        if self._ready_callback is not None:
            log.warning("when_claude_ready: callback anterior substituído")
            if self._ready_timeout is not None:
                self._ready_timeout.stop()
        self._ready_callback = callback
        self._ready_timeout = QTimer(self)
        self._ready_timeout.setSingleShot(True)
        self._ready_timeout.timeout.connect(lambda: self._fire_ready_callback(False))
        self._ready_timeout.start(timeout_ms)

    def _fire_ready_callback(self, success: bool) -> None:
        cb = self._ready_callback
        self._ready_callback = None
        if self._ready_timeout is not None:
            self._ready_timeout.stop()
            self._ready_timeout = None
        if cb is not None:
            try:
                cb(success)
            except Exception:
                log.exception("Falha no callback de when_claude_ready")

    def _on_session_finished(self) -> None:
        self._status.setText("(processo encerrado)")
        self._stop_btn.setEnabled(False)
        self._set_running(False)

    def start_command(self, argv: list[str], cwd: str, label: str | None = None) -> None:
        if not self._bridge_ready:
            log.info("Bridge ainda não pronto, agendando comando")
            self._pending = (argv, cwd, label)
            self._status.setText(f"(carregando) {label or argv[0]}")
            return
        self._start_now(argv, cwd, label)

    def _start_now(self, argv: list[str], cwd: str, label: str | None = None) -> None:
        if self.session.is_running():
            self.session.terminate()
        try:
            self.session.start(argv, cwd)
        except OSError as e:
            log.exception("Falha ao iniciar pty")
            self._status.setText(f"(erro) {e}")
            return
        self._status.setText(label or " ".join(argv))
        self._stop_btn.setEnabled(True)
        self._set_running(True)

    def start_shell_command(
        self,
        inner_argv: list[str],
        cwd: str,
        label: str | None = None,
        shell: str | None = None,
    ) -> None:
        """Roda comando através do shell interativo para que aliases
        (e.g. `ia` → `claude`) resolvam. Sem `shell`, usa o shell de
        login do /etc/passwd (não o `$SHELL` herdado, que pode estar
        sobrescrito pelo processo pai)."""
        shell = shell or _login_shell()
        inner = shlex.join(inner_argv)
        self.start_command([shell, "-ic", inner], cwd, label or inner)

    def start_interactive_shell(self, cwd: str, shell: str | None = None) -> None:
        shell = shell or _login_shell()
        self.start_command([shell, "-i"], cwd, label=shell)

    def terminate(self) -> None:
        if self.session.is_running():
            self.session.terminate()
        self._stop_btn.setEnabled(False)
        self._status.setText("(terminal vazio)")
        self._set_running(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Debounced — durante drag de splitter o resizeEvent dispara dezenas
        # de vezes; queremos refitar só quando para
        self._fit_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Show é raro o suficiente pra disparar direto (sem debounce)
        if hasattr(self, "bridge") and self._bridge_ready:
            self.bridge.force_fit_requested.emit()

    def _emit_force_fit(self) -> None:
        if hasattr(self, "bridge") and self._bridge_ready:
            self.bridge.force_fit_requested.emit()

    def closeEvent(self, event) -> None:
        self.terminate()
        super().closeEvent(event)
