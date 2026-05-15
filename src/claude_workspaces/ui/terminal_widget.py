import logging
import os
import pwd
import shlex
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_running = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel("(terminal vazio)")
        self._status.setStyleSheet("color: #888;")
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        self._stop_btn = QPushButton("Encerrar")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.terminate)
        toolbar.addWidget(self._stop_btn)
        outer.addLayout(toolbar)

        self.session = PtySession(self)
        self.session.finished.connect(self._on_session_finished)

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

    def is_running(self) -> bool:
        return self._is_running

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
        # Qt mudou nosso tamanho — o ResizeObserver no JS normalmente já
        # pega isso, mas em alguns casos (split inicial, troca de aba do
        # QStackedWidget, mudança de zoom do Qt) o evento não propaga.
        # Disparar o sinal force_fit_requested garante um refit explícito.
        if hasattr(self, "bridge") and self._bridge_ready:
            self.bridge.force_fit_requested.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if hasattr(self, "bridge") and self._bridge_ready:
            self.bridge.force_fit_requested.emit()

    def closeEvent(self, event) -> None:
        self.terminate()
        super().closeEvent(event)
