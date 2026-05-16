import fcntl
import logging
import os
import pty
import signal
import struct
import termios

from PySide6.QtCore import QObject, QSocketNotifier, Signal

log = logging.getLogger(__name__)


class PtySession(QObject):
    output_received = Signal(bytes)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pid: int | None = None
        self.master_fd: int | None = None
        self._notifier: QSocketNotifier | None = None

    def is_running(self) -> bool:
        return self.pid is not None

    def start(
        self,
        argv: list[str],
        cwd: str,
        env: dict[str, str] | None = None,
    ) -> None:
        if self.pid is not None:
            self.terminate()

        log.info("Starting pty: %s (cwd=%s)", argv, cwd)
        try:
            pid, master_fd = pty.fork()
        except OSError:
            log.exception("pty.fork falhou")
            raise

        if pid == 0:
            # No child do fork: NÃO podemos usar logging normal (handlers
            # do parent não funcionam no child). Errors aqui escrevem
            # direto em stderr e saem com 127 (convenção de exec failure).
            try:
                os.chdir(cwd)
            except OSError as e:
                os.write(2, f"pty child: chdir({cwd}) falhou: {e}\n".encode())
            new_env = os.environ.copy()
            if env:
                new_env.update(env)
            new_env.setdefault("TERM", "xterm-256color")
            new_env.setdefault("COLORTERM", "truecolor")
            try:
                os.execvpe(argv[0], argv, new_env)
            except Exception as e:
                os.write(2, f"pty child: exec({argv[0]}) falhou: {e}\n".encode())
                os._exit(127)

        self.pid = pid
        self.master_fd = master_fd

        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._notifier = QSocketNotifier(master_fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_readable)

    def _on_readable(self) -> None:
        if self.master_fd is None:
            return
        try:
            data = os.read(self.master_fd, 8192)
        except (BlockingIOError, OSError):
            data = b""

        if not data:
            log.info("pty %s atingiu EOF", self.pid)
            self._cleanup()
            self.finished.emit()
            return

        self.output_received.emit(data)

    def write(self, data: bytes) -> None:
        if self.master_fd is None:
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            log.warning("Falha ao escrever no pty (pid=%s)", self.pid)

    def resize(self, cols: int, rows: int) -> None:
        if self.master_fd is None or cols <= 0 or rows <= 0:
            return
        size = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    def terminate(self) -> None:
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except OSError:
                pass
        self._cleanup()

    def _cleanup(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        if self.pid is not None:
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except OSError:
                pass
            self.pid = None
