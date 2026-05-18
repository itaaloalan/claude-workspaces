import logging
import os
import pwd
import shlex
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
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
    # status_text, is_working, needs_decision
    activity_changed = Signal(str, bool, bool)
    # Emitido quando o terminal resolve/reivindica um session_id de Claude.
    # Permite ao painel embutido de runners atualizar seu filtro pra mostrar
    # apenas runners daquele console.
    claimed_session_id_changed = Signal(str)
    # Solicita ao MainWindow criar/anexar o painel de runners embutido.
    # MainWindow constrói a RunnerArea com o session_id atual e chama
    # `set_runner_panel`. Sem essa indireção, o TerminalWidget precisaria
    # conhecer Workspace/Settings, quebrando o nível de abstração.
    runner_panel_toggle_requested = Signal()

    # IDs de sessões já reivindicadas por outros TerminalWidgets vivos.
    # Why: dois terminais no mesmo cwd disputam o mesmo dir de JSONLs e
    # o critério "mtime mais recente" devolve a sessão da aba mais ativa
    # — bug em que a aba 2 mostrava o título da aba 1.
    _claimed_session_ids: set[str] = set()
    # Debounce global da transição working→idle. Atualizado por
    # `set_idle_debounce_seconds` quando o usuário muda em Settings;
    # todos os terminais vivos passam a usar o novo valor no próximo poll.
    _idle_debounce_s: float = 20.0

    @classmethod
    def set_idle_debounce_seconds(cls, seconds: float) -> None:
        cls._idle_debounce_s = max(0.0, min(120.0, float(seconds)))

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
        self._last_needs_decision = False
        self._activity_dirty = False
        # Debounce working→idle: o parser oscila entre is_working True/False
        # durante o mesmo turno (tool calls intercalando com texto). Aguarda
        # N segundos estáveis em "não-working" antes de propagar pra UI, pra
        # evitar flicker de "Trabalhando ↔ Ocioso". O valor vem do setting
        # `idle_debounce_seconds` (class attr `_idle_debounce_s`, lido a
        # cada poll — assim mudanças em Settings afetam todos os terminais
        # vivos sem reinicialização).
        self._pending_idle_since: float | None = None
        # Marco de quando o terminal entrou em estado running (PTY ativa).
        # Nos primeiros segundos depois do start, o parser oscila por
        # causa do output inicial do TUI (boot, render, resume). Durante
        # essa janela de graça (`_STARTUP_GRACE_S`), o debounce é
        # ignorado — se o parser diz "Ocioso", a UI mostra "Ocioso"
        # direto. Without this, reabrir o app deixa todas as sessões
        # presas em "Trabalhando" por `idle_debounce_seconds` mesmo
        # quando o Claude já está no prompt principal.
        self._running_since: float = 0.0
        self._STARTUP_GRACE_S = 3.0
        # Context Claude (cwd + resume) pra descobrir o título da sessão
        # via scan do ~/.claude/projects/<cwd>/*.jsonl
        self._claude_cwd: str | None = None
        self._claude_resume_id: str | None = None
        self._claude_start_time: float = 0.0
        self._session_preview: str | None = None
        self._session_resolved: bool = False
        # IDs presentes no dir ANTES do nosso start — qualquer um deles
        # não é nosso, mesmo que esteja sendo atualizado agora (outra aba)
        self._pre_existing_session_ids: set[str] = set()
        # ID que reivindicamos pro registry global; usado pra liberar quando
        # o terminal é destruído
        self._claimed_session_id: str | None = None
        # Sinaliza que esta sessão foi reaberta no startup (--resume após
        # fechar/abrir o app). Usado pra decidir se o botão ▶ continuar
        # faz sentido — em sessão nova/fresh não há nada pra continuar e
        # o botão vira ruído. Set por main_window._restore_sessions.
        self._restored_on_startup: bool = False
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
        self._continue_btn = QPushButton("▶ Continuar")
        self._continue_btn.setEnabled(False)
        # Começa oculto — só vira visível quando a sessão foi restaurada
        # no startup (--resume) e está em estado "Ocioso". Em sessão nova
        # iniciada no app, "continue" não tem o que continuar.
        self._continue_btn.setVisible(False)
        self._continue_btn.setToolTip(
            "Manda 'continue' para o Claude — útil quando ele parou no meio "
            "de uma tarefa (ex: ao reabrir uma sessão com --resume)"
        )
        self._continue_btn.clicked.connect(self.send_continue)
        toolbar.addWidget(self._continue_btn)
        self._mode_btn = QPushButton("⚙ Modo")
        self._mode_btn.setEnabled(False)
        self._mode_btn.setToolTip(
            "Trocar modo (plan/auto/…), effort ou modelo desta sessão"
        )
        self._mode_btn.clicked.connect(self._open_mode_popup)
        toolbar.addWidget(self._mode_btn)
        self._runners_btn = QPushButton("▤ Runners")
        self._runners_btn.setCheckable(True)
        self._runners_btn.setToolTip(
            "Mostrar/ocultar painel de runners deste console. Runners criados "
            "aqui pertencem só a esta aba — pode rodar várias instâncias "
            "(branches/portas diferentes) sem conflito com outros consoles."
        )
        self._runners_btn.clicked.connect(self._on_runners_toggle)
        toolbar.addWidget(self._runners_btn)
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

        # Splitter vertical: topo = xterm; rodapé (opcional) = painel de
        # runners do console. O painel é criado sob demanda (lazy) na
        # primeira vez que o botão "▤ Runners" é clicado — assim consoles
        # que nunca usam runners não pagam o custo de instanciar a área.
        self._main_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._main_splitter.addWidget(self.view)
        self._runner_panel_host = QWidget()
        self._runner_panel_host_layout = QVBoxLayout(self._runner_panel_host)
        self._runner_panel_host_layout.setContentsMargins(0, 0, 0, 0)
        self._runner_panel_host_layout.setSpacing(0)
        self._runner_panel_host.setVisible(False)
        self._main_splitter.addWidget(self._runner_panel_host)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._runner_panel: QWidget | None = None
        outer.addWidget(self._main_splitter, stretch=1)

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
                self._running_since = time.monotonic()
                self._activity_timer.start()
            else:
                self._activity_timer.stop()
                # Emite estado final "idle" pra UI limpar o spinner
                self.activity_changed.emit("(encerrado)", False, False)

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
        # Snapshot dos JSONLs já existentes — qualquer um que apareça aqui
        # NÃO é nossa sessão (ou é resume, tratado pelo branch separado)
        if resume_id is None:
            try:
                from ..claude_sessions import list_sessions
                self._pre_existing_session_ids = {
                    s.id for s in list_sessions(cwd, limit=50)
                }
            except Exception:
                log.debug("snapshot pré-existente falhou", exc_info=True)
                self._pre_existing_session_ids = set()
        else:
            self._pre_existing_session_ids = set()

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
            sessions = list_sessions(self._claude_cwd, limit=20)
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
                    self._claim_session(s.id)
                    return
            return
        # Sessão nova — exclui (a) JSONLs que já existiam ANTES do nosso
        # start e (b) IDs já reivindicados por outros TerminalWidgets vivos.
        # Sem esses filtros, duas abas no mesmo cwd disputavam o mesmo
        # JSONL e a segunda exibia o título da primeira.
        candidates = [
            s for s in sessions
            if s.id not in self._pre_existing_session_ids
            and s.id not in TerminalWidget._claimed_session_ids
            and s.mtime >= self._claude_start_time - 5
        ]
        if not candidates:
            return
        # Desempate: a sessão recém-criada tem mtime próximo do nosso start.
        # Sessões "alheias" sendo escritas no mesmo cwd têm mtime drift maior.
        candidates.sort(key=lambda s: abs(s.mtime - self._claude_start_time))
        chosen = candidates[0]
        # Reivindica já — antes do preview resolver — pra evitar que outro
        # terminal disputando o mesmo dir pegue esse ID na próxima tick
        self._claim_session(chosen.id)
        preview = chosen.preview or ""
        if preview:
            self._session_preview = preview
            self._session_resolved = True

    def _claim_session(self, session_id: str) -> None:
        if self._claimed_session_id == session_id:
            return
        if self._claimed_session_id is not None:
            TerminalWidget._claimed_session_ids.discard(self._claimed_session_id)
        self._claimed_session_id = session_id
        TerminalWidget._claimed_session_ids.add(session_id)
        # Informa o painel embutido (e MainWindow) que o session_id mudou —
        # runners criados antes da resolução são re-stampados pra apontar
        # pro id estável da sessão.
        self.claimed_session_id_changed.emit(session_id)

    def release_session_claim(self) -> None:
        """Chamado quando o terminal é descartado — libera o ID claimed
        pro próximo terminal poder reusar se for o caso (resume futuro)."""
        if self._claimed_session_id is not None:
            TerminalWidget._claimed_session_ids.discard(self._claimed_session_id)
            self._claimed_session_id = None

    def claimed_session_id(self) -> str | None:
        """ID da sessão JSONL atualmente vinculada (resolvida pelo scan ou
        passada via configure_claude com resume). Usado pelo restore na
        próxima execução pra retomar via `claude --resume`."""
        return self._claimed_session_id or self._claude_resume_id

    def claude_cwd(self) -> str | None:
        """cwd usado pra rodar Claude — necessário pro --resume casar o
        diretório do JSONL no ~/.claude/projects/."""
        return self._claude_cwd

    def claimed_session_path(self) -> Path | None:
        """Caminho absoluto do JSONL da sessão atualmente vinculada, ou
        None se ainda não foi resolvida. Usado pra computar usage stats
        no menu de contexto."""
        sid = self.claimed_session_id()
        if not sid or not self._claude_cwd:
            return None
        from ..claude_sessions import project_sessions_dir
        p = project_sessions_dir(self._claude_cwd) / f"{sid}.jsonl"
        return p if p.exists() else None

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
            # Importante: não retorna se há debounce idle pendente — precisamos
            # continuar parsando pra detectar se o Claude voltou a trabalhar
            # ou se os 5s estabilizaram.
            if self._pending_idle_since is None:
                return
        self._activity_dirty = False
        activity = parse_status(bytes(self._output_buffer), age)

        # Debounce working→idle. Working→awaiting (needs_decision) passa
        # direto: o usuário precisa de feedback imediato quando o Claude
        # pede uma decisão. Quando o debounce é 0, vira idle imediatamente
        # (modo antigo, sem debounce).
        # Janela de graça pós-startup: nos primeiros _STARTUP_GRACE_S após
        # o PTY entrar em running, o debounce é ignorado. Isso permite
        # que reabrir o app com sessões já no prompt mostre "Ocioso"
        # imediatamente em vez de ficar 20s em "Trabalhando" por causa
        # do flicker inicial do parser durante o render do TUI.
        now = time.monotonic()
        debounce_s = type(self)._idle_debounce_s
        in_startup_grace = (
            self._running_since > 0
            and (now - self._running_since) < self._STARTUP_GRACE_S
        )
        if (
            debounce_s > 0
            and not in_startup_grace
            and self._last_working
            and not activity.is_working
            and not activity.needs_decision
        ):
            if self._pending_idle_since is None:
                self._pending_idle_since = now
            if now - self._pending_idle_since < debounce_s:
                # Suprime emit — UI continua mostrando "Trabalhando".
                # Se status mudar (ex: nova ação), também não emite, pra
                # não atualizar a sub-linha enquanto a transição flutua.
                return
            # N segundos estáveis sem voltar a working: pode realmente
            # virar idle.
            self._pending_idle_since = None
        else:
            # Voltou a working, ou já estava idle, ou virou awaiting, ou
            # debounce desligado: cancela qualquer debounce pendente.
            self._pending_idle_since = None

        if (
            activity.status != self._last_status
            or activity.is_working != self._last_working
            or activity.needs_decision != self._last_needs_decision
        ):
            self._last_status = activity.status
            self._last_working = activity.is_working
            self._last_needs_decision = activity.needs_decision
            self.activity_changed.emit(
                activity.status, activity.is_working, activity.needs_decision
            )
            self._refresh_continue_visibility()

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
        self._continue_btn.setEnabled(False)
        self._continue_btn.setVisible(False)
        self._mode_btn.setEnabled(False)
        self._set_running(False)

    def send_text(self, text: str, submit: bool = True) -> None:
        """Envia texto direto pro PTY como se o usuário tivesse digitado.
        Com submit=True (default), adiciona '\\r' no fim — equivalente a
        apertar Enter, fazendo Claude (ou qualquer TUI) submeter a linha.

        Why: ao reabrir o app, sessões Claude com --resume ficam paradas
        no prompt esperando input mesmo quando estavam no meio de uma
        tarefa. Mandar 'continue' destrava sem ter que focar a aba e
        digitar manualmente em cada console."""
        if not self.session.is_running():
            return
        data = text + ("\r" if submit else "")
        self.session.write(data.encode("utf-8"))

    def send_continue(self) -> None:
        """Atalho — manda 'continue' + Enter pra retomar trabalho do Claude."""
        self.send_text("continue")

    def mark_restored_on_startup(self) -> None:
        """Marca esta sessão como restaurada no startup (--resume após
        reabrir o app). Habilita o botão ▶ continuar quando o estado for
        ocioso — em sessão nova/iniciada no app o botão permanece oculto
        porque não há tarefa interrompida pra retomar."""
        self._restored_on_startup = True
        self._refresh_continue_visibility()

    def was_restored_on_startup(self) -> bool:
        return self._restored_on_startup

    def _refresh_continue_visibility(self) -> None:
        """Mostra o ▶ Continuar só em sessão restaurada+ociosa. Sem
        restaurada, fica oculto pra sempre. Sem ocioso, oculto até o
        Claude voltar ao prompt."""
        idle = (
            self._is_running
            and not self._last_working
            and not self._last_needs_decision
        )
        self._continue_btn.setVisible(self._restored_on_startup and idle)

    def send_cycle_mode(self) -> None:
        """Manda Shift+Tab (CSI Z) — cicla entre os modos do Claude Code
        (default → auto-accept → plan)."""
        if not self.session.is_running():
            return
        self.session.write(b"\x1b[Z")

    def send_open_model(self) -> None:
        """Abre o picker `/model` no prompt do Claude (com Enter)."""
        self.send_text("/model")

    def send_open_effort(self) -> None:
        """Abre o picker `/effort` no prompt do Claude (com Enter)."""
        self.send_text("/effort")

    def _open_mode_popup(self) -> None:
        """Mostra o ModePopup ancorado abaixo do botão ⚙ Modo."""
        from .mode_popup import ModePopup

        if not self.session.is_running():
            return
        popup = ModePopup(
            on_cycle=self.send_cycle_mode,
            on_effort=self.send_open_effort,
            on_model=self.send_open_model,
            parent=self,
        )
        # Ancorar abaixo-direita do botão (estilo dropdown)
        anchor = self._mode_btn.mapToGlobal(
            self._mode_btn.rect().bottomRight()
        )
        # Desloca pra que a direita do popup alinhe com a direita do botão
        anchor.setX(anchor.x() - popup.sizeHint().width())
        anchor.setY(anchor.y() + 4)
        popup.show_at(anchor)

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
        self._continue_btn.setEnabled(True)
        self._mode_btn.setEnabled(True)
        self._set_running(True)
        # Avalia visibilidade do ▶ — depende de restored_on_startup +
        # estado idle. Quem chama esse método é o launch flow; restore
        # marca o flag logo em seguida via mark_restored_on_startup.
        self._refresh_continue_visibility()

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
        self._continue_btn.setEnabled(False)
        self._continue_btn.setVisible(False)
        self._mode_btn.setEnabled(False)
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

    def _on_runners_toggle(self) -> None:
        # Primeira vez: pede ao MainWindow pra construir e anexar o painel.
        if self._runner_panel is None:
            self.runner_panel_toggle_requested.emit()
            # Se o slot anexou um painel, mostra-o; caso contrário desmarca.
            visible = self._runner_panel is not None
            self._runners_btn.setChecked(visible)
            if visible:
                self._show_runner_panel()
            return
        # Já existe: alterna visibilidade.
        if self._runner_panel_host.isVisible():
            self._runner_panel_host.setVisible(False)
            self._runners_btn.setChecked(False)
        else:
            self._show_runner_panel()
            self._runners_btn.setChecked(True)

    def _show_runner_panel(self) -> None:
        self._runner_panel_host.setVisible(True)
        # Divide ~70/30 quando o painel é mostrado pela primeira vez.
        total = max(self._main_splitter.height(), 400)
        self._main_splitter.setSizes([int(total * 0.7), int(total * 0.3)])

    def set_runner_panel(self, panel: QWidget | None) -> None:
        """Anexa (ou desanexa) o painel de runners embutido neste terminal."""
        # Remove o antigo, se houver — não destrói (o caller controla o ciclo).
        if self._runner_panel is not None:
            self._runner_panel_host_layout.removeWidget(self._runner_panel)
            self._runner_panel.setParent(None)
            self._runner_panel = None
        if panel is not None:
            self._runner_panel_host_layout.addWidget(panel)
            self._runner_panel = panel

    def runner_panel(self) -> QWidget | None:
        return self._runner_panel

    def closeEvent(self, event) -> None:
        self.terminate()
        super().closeEvent(event)
