import fcntl
import logging
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios

from PySide6.QtCore import QObject, QSocketNotifier, Signal

log = logging.getLogger(__name__)

# Slice do systemd (--user) onde cada runner ganha seu PRÓPRIO scope/cgroup.
# Sem isso, todo runner herda o cgroup do app e o systemd-oomd, ao mirar o
# conjunto sob pressão de swap, derruba o app inteiro (GUI + todos os runners)
# de uma vez. Com cada runner num cgroup isolado, o oomd recicla UM runner
# descontrolado e o GUI (no cgroup do próprio serviço) segue vivo e protegido.
_RUNNER_SLICE = "cw-runners.slice"
_CONSOLE_SLICE = "cw-consoles.slice"
_scope_supported: bool | None = None


def _scope_prefix(cwd: str, slice_name: str = _RUNNER_SLICE) -> list[str] | None:
    """Prefixo `systemd-run --user --scope` que põe o processo num cgroup próprio
    (sob a slice `slice_name`: runners e consoles em slices distintas pra permitir
    política de oomd diferenciada depois),
    ou None se o isolamento não estiver disponível (sem systemd-run ou sem
    manager de usuário — aí o caller faz o spawn direto, como antes).

    Por que é transparente pro kill/reap: `--scope` faz `exec()` do comando (não
    deixa um supervisor no meio), então o pid forkado continua sendo o
    session-leader do `bash` — killpg(pid) e waitpid(pid) seguem idênticos.
    `--scope` também herda env e cwd do processo. Checado uma vez e cacheado."""
    global _scope_supported
    if _scope_supported is None:
        ok = False
        if shutil.which("systemd-run"):
            try:
                r = subprocess.run(
                    ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                     "--slice=" + _RUNNER_SLICE, "true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                ok = r.returncode == 0
            except Exception:
                ok = False
        _scope_supported = ok
        log.info("isolamento de runner em cgroup (systemd-run --scope): %s",
                 "ativo" if ok else "indisponível (spawn direto)")
    if not _scope_supported:
        return None
    return [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "--slice=" + slice_name,
        "--working-directory=" + cwd,
        "--",
    ]


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

    @property
    def cols(self) -> int:
        """Colunas do último resize pedido (80 default, antes do primeiro fit)."""
        return self._pending_size[0] if self._pending_size else 80

    @property
    def rows(self) -> int:
        """Linhas do último resize pedido (24 default, antes do primeiro fit)."""
        return self._pending_size[1] if self._pending_size else 24

    def start(
        self,
        argv: list[str],
        cwd: str,
        env: dict[str, str] | None = None,
        kill_group_on_replace: bool = True,
        isolate: bool = False,
        isolate_slice: str = _RUNNER_SLICE,
    ) -> None:
        if self.pid is not None:
            self.terminate(kill_group=kill_group_on_replace)

        # Isola o runner num cgroup próprio (systemd-run --user --scope) pra que
        # o oomd possa reciclá-lo sozinho sem derrubar o app. Transparente pro
        # kill/reap (--scope faz exec, o pid forkado segue session-leader do
        # bash). Cai no spawn direto se o isolamento não estiver disponível.
        if isolate:
            prefix = _scope_prefix(cwd, isolate_slice)
            if prefix is not None:
                argv = prefix + argv

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

        # Métricas de throughput + custo total dos handlers downstream
        # (record_output, filtro do bridge, detecção de URL…) que rodam
        # síncronos neste emit. É o ponto único por onde TODO output de PTY
        # (consoles + runners) passa.
        from . import perf
        perf.count("pty.reads")
        perf.count("pty.bytes", len(data))
        with perf.timed("pty.emit_handlers"):
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

    def terminate(self, kill_group: bool = True) -> None:
        """Mata o processo do pty e (por padrão) tudo abaixo dele.

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

        Why kill_group=False existe: quando um runner roda um comando
        substituto no mesmo PTY (stop_cmd/restart_cmd), é esse comando
        que gerencia o serviço de fundo — matar o grupo inteiro derruba
        o serviço junto (o SIGKILL do fallback matava o DAS do GlassFish
        antes do `asadmin redeploy` do restart_cmd rodar). No modo soft,
        só o filho direto (tipicamente um `tail -F`) morre; processos
        foreground pendurados ainda caem via SIGHUP do kernel quando o
        session leader sai.
        """
        pid = self.pid
        if pid is not None:
            try:
                if kill_group:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
                self._schedule_sigkill(pid, kill_group=kill_group)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                    self._schedule_sigkill(pid, kill_group=False)
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

    def _schedule_sigkill(self, pid: int, kill_group: bool = True) -> None:
        from PySide6.QtCore import QTimer

        def _kill() -> None:
            if not kill_group:
                # Modo soft (comando substituto): SIGKILL só no filho
                # direto — o resto do grupo (serviço de fundo) fica vivo.
                try:
                    os.kill(pid, 0)
                except OSError:
                    return  # processo já morreu/reaped
                log.warning("pid=%s não respondeu a SIGTERM, enviando SIGKILL", pid)
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                return
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
            pid = self.pid
            self.pid = None
            # Reap não-bloqueante: uma tentativa WNOHANG já pega o exit code
            # no caso comum (filho já morto). Sob carga, o EOF do pty chega
            # ANTES do exit status ficar pronto e o WNOHANG devolve (0, 0) —
            # nesse caso NÃO abandonamos o filho: agendamos reaping assíncrono
            # que insiste até recolher. O bug antigo desistia em 50ms (com
            # time.sleep bloqueando a UI) e zerava o pid, deixando o processo
            # como zumbi <defunct> pra sempre (ninguém mais dava wait()).
            if not self._reap(pid):
                self.last_exit_code = -1
                self._schedule_reap(pid)

    def _reap(self, pid: int) -> bool:
        """Tenta recolher `pid` sem bloquear (WNOHANG). Atualiza
        last_exit_code se conseguir. Retorna True se recolheu (ou se o filho
        já não é nosso/já foi recolhido), False se ainda está vivo."""
        try:
            wait_pid, wait_status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True  # já recolhido por outro waiter
        except OSError:
            return True  # nada que possamos fazer
        if wait_pid == 0:
            return False  # ainda rodando / status indisponível
        # POSIX status: low byte = sinal/0, alto byte = exit code.
        if os.WIFEXITED(wait_status):
            self.last_exit_code = os.WEXITSTATUS(wait_status)
        elif os.WIFSIGNALED(wait_status):
            # Convenção shell: 128 + nº do sinal pra distinguir de exit
            # codes "normais".
            self.last_exit_code = 128 + os.WTERMSIG(wait_status)
        else:
            self.last_exit_code = -1
        return True

    def _schedule_reap(self, pid: int, attempts: int = 0) -> None:
        """Reaping assíncrono e não-bloqueante: insiste em WNOHANG via QTimer
        até o filho ser recolhido, evitando zumbis sob carga (o processo já
        morreu; é só questão de o kernel publicar o exit status). Backoff
        suave (50ms no 1º segundo, depois 500ms) e teto alto de salvaguarda
        pra nunca virar timer eterno."""
        from PySide6.QtCore import QTimer

        if self._reap(pid):
            return
        if attempts >= 600:
            log.warning("desisti de reapear pid %s após %d tentativas", pid, attempts)
            return
        delay = 50 if attempts < 20 else 500
        QTimer.singleShot(delay, lambda: self._schedule_reap(pid, attempts + 1))
