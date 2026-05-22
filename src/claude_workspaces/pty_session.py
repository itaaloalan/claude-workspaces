import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time

from PySide6.QtCore import QObject, QSocketNotifier, Signal

log = logging.getLogger(__name__)


class PtySession(QObject):
    output_received = Signal(bytes)
    finished = Signal()
    # Variante com exit code (POSIX status, ou -1 quando indeterminado:
    # cleanup chamado sem reap, ou waitpid não encontrou nada).
    # Convenção: 0 = sucesso; >0 = falha; -1 = desconhecido. Listeners
    # que precisam diferenciar success/failure conectam aqui; o sinal
    # `finished` (sem arg) continua existindo pra back-compat.
    finished_with_status = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pid: int | None = None
        self.master_fd: int | None = None
        self._notifier: QSocketNotifier | None = None
        # Exit code da última execução (None enquanto rodando ou nunca rodou).
        # Lido pelos listeners de `finished` que querem o status sem se
        # conectar ao sinal extra.
        self.last_exit_code: int | None = None
        # Último tamanho pedido pelo frontend xterm.js. Pode chegar ANTES
        # do start() (resize via WebChannel é assíncrono e o JS faz fit
        # antes da gente forkar) — guardamos pra aplicar pós-fork e evitar
        # que Claude/TUI renderize com 80 colunas default.
        self._pending_size: tuple[int, int] | None = None

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

        # Aplica resize pendente imediatamente — antes que SIGWINCH seja
        # necessário, o kernel já entrega o tamanho correto via ioctl pro
        # próximo `tcgetattr`/leitura de winsize do filho recém-execado.
        if self._pending_size is not None:
            cols, rows = self._pending_size
            self._apply_size(cols, rows)

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
            self.finished_with_status.emit(self.last_exit_code if self.last_exit_code is not None else -1)
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
        if cols <= 0 or rows <= 0:
            return
        self._pending_size = (cols, rows)
        if self.master_fd is None:
            return
        self._apply_size(cols, rows)

    def _apply_size(self, cols: int, rows: int) -> None:
        if self.master_fd is None:
            return
        size = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    def terminate(self) -> None:
        """Mata o processo do pty e tudo abaixo dele.

        Why killpg em vez de kill: programas como `npm start` rodam um
        node filho — SIGHUP só no bash/npm wrapper deixa o node solto,
        ocupando a porta. Como pty.fork() coloca o filho como session
        leader, a PID dele é também a PGID; killpg pega todos os
        descendentes em um sweep.

        Why SIGTERM antes de SIGKILL: dá ao processo chance de cleanup
        (fechar sockets, flush de logs). SIGKILL é fallback se o group
        ainda existe ~600ms depois — agendado via QTimer pra não
        bloquear a UI. Sem o fallback, asadmin/java do GlassFish ficava
        órfão entre restarts do app.
        """
        pid = self.pid
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGTERM)
                self._schedule_sigkill(pid)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                    self._schedule_sigkill(pid)
                except OSError:
                    pass
        # Cleanup do FD/notifier — depois disso o filho perde o
        # controlling tty, então qualquer processo restante recebe
        # SIGHUP em reads/writes ao stdio.
        had_pid = self.pid is not None
        self._cleanup()
        # Garante que listeners (RunnerWidget._on_session_finished) saem
        # de "running" mesmo quando o stop é iniciado pelo app — sem
        # isso, a UI fica travada no estado anterior porque _cleanup
        # zera o pid mas não emite `finished`.
        if had_pid:
            self.finished.emit()
            self.finished_with_status.emit(self.last_exit_code if self.last_exit_code is not None else -1)

    def _schedule_sigkill(self, pid: int) -> None:
        from PySide6.QtCore import QTimer

        def _kill() -> None:
            try:
                os.killpg(pid, 0)
            except OSError:
                return  # grupo já morreu
            log.warning("pgid=%s não respondeu a SIGTERM, enviando SIGKILL", pid)
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        QTimer.singleShot(600, _kill)

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
                # Loop curto pra dar chance do filho ser reaped — sob carga
                # do KDE/Wayland, o socket EOF chega antes do exit status
                # estar disponível e WNOHANG devolve (0, 0). Tentamos com
                # WNOHANG umas poucas vezes e desistimos rapido pra não
                # bloquear o event loop.
                wait_pid = 0
                wait_status = 0
                for _ in range(5):
                    wait_pid, wait_status = os.waitpid(self.pid, os.WNOHANG)
                    if wait_pid != 0:
                        break
                    time.sleep(0.01)
                if wait_pid != 0:
                    # POSIX status: low byte = sinal/0, alto byte = exit code.
                    if os.WIFEXITED(wait_status):
                        self.last_exit_code = os.WEXITSTATUS(wait_status)
                    elif os.WIFSIGNALED(wait_status):
                        # Convenção shell: 128 + nº do sinal pra distinguir
                        # de exit codes "normais".
                        self.last_exit_code = 128 + os.WTERMSIG(wait_status)
                    else:
                        self.last_exit_code = -1
                else:
                    self.last_exit_code = -1
            except OSError:
                self.last_exit_code = -1
            self.pid = None
