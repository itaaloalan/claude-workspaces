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
    QSizePolicy,
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
    clear_requested = Signal()
    ready = Signal()

    def __init__(self, session: PtySession) -> None:
        super().__init__()
        self.session = session
        self.session.output_received.connect(self._on_pty_output)
        # Filtro opcional aplicado linha a linha (substring case-insensitive
        # após strip de ANSI). Vazio = pass-through. Usado pelo RunnerWidget
        # pra filtrar logs sem perder o buffer completo (replay).
        self._filter_text: str = ""
        self._line_buf: bytearray = bytearray()

    def _on_pty_output(self, data: bytes) -> None:
        if not self._filter_text:
            # Sem filtro: pass-through. Se havia parcial bufferizado por
            # um filtro anterior, devolve antes pra não perder bytes.
            if self._line_buf:
                pending = bytes(self._line_buf)
                self._line_buf.clear()
                self.output_to_terminal.emit(pending + data)
            else:
                self.output_to_terminal.emit(data)
            return
        self._line_buf.extend(data)
        out = bytearray()
        while True:
            idx = self._line_buf.find(b"\n")
            if idx < 0:
                break
            line = bytes(self._line_buf[: idx + 1])
            del self._line_buf[: idx + 1]
            if self._line_matches(line):
                out.extend(line)
        if out:
            self.output_to_terminal.emit(bytes(out))

    def set_filter(self, text: str) -> None:
        """Define o filtro de linhas. Vazio = sem filtro (pass-through)."""
        self._filter_text = (text or "").strip().lower()

    def replay_filtered(self, full_log: str) -> None:
        """Limpa o terminal e re-emite `full_log` aplicando o filtro atual.
        Resets também o buffer de linha parcial — chamada típica após o
        usuário mudar o filtro."""
        self.clear_requested.emit()
        self._line_buf.clear()
        if not full_log:
            return
        data = full_log.encode("utf-8", errors="replace")
        if not self._filter_text:
            self.output_to_terminal.emit(data)
            return
        out = bytearray()
        for line in data.splitlines(keepends=True):
            if self._line_matches(line):
                out.extend(line)
        if out:
            self.output_to_terminal.emit(bytes(out))

    def _line_matches(self, line: bytes) -> bool:
        if not self._filter_text:
            return True
        try:
            text = line.decode("utf-8", errors="replace")
        except Exception:
            return False
        # Match após strip de ANSI pra que "error" case com linhas
        # coloridas (\x1b[31merror\x1b[0m).
        from ..services.runner_url_detect import strip_ansi
        return self._filter_text in strip_ansi(text).lower()

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
    # Exit code do PTY quando a sessão termina (0=success, >0=fail, -1=desconhecido).
    # MainWindow conecta pra emitir task_completed/task_failed no NotificationService.
    session_exited = Signal(int)
    # Emitido quando o terminal resolve/reivindica um session_id de Claude.
    # Permite ao painel embutido de runners atualizar seu filtro pra mostrar
    # apenas runners daquele console.
    claimed_session_id_changed = Signal(str)
    # Solicita ao MainWindow criar/anexar o painel de runners embutido.
    # MainWindow constrói a RunnerArea com o session_id atual e chama
    # `set_runner_panel`. Sem essa indireção, o TerminalWidget precisaria
    # conhecer Workspace/Settings, quebrando o nível de abstração.
    runner_panel_toggle_requested = Signal()
    # Emitido quando uma URL de PR do GitHub é detectada no output pela
    # primeira vez na sessão. Propaga pra sidebar e status bar via MainWindow.
    pr_detected = Signal(str)

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
        self._needs_decision_held = False
        self._is_plan_mode = False
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
        # Nome custom escolhido pelo usuário via "✏ Renomear sessão" no menu
        # de contexto. Tem precedência sobre `_session_preview` no
        # `effective_title()`. Persistido em `session_marks.json` por
        # session_id assim que a sessão é reivindicada.
        self._custom_name: str = ""
        # Sinaliza que esta sessão foi reaberta no startup (--resume após
        # fechar/abrir o app). Usado pra decidir se o botão ▶ continuar
        # faz sentido — em sessão nova/fresh não há nada pra continuar e
        # o botão vira ruído. Set por main_window._restore_sessions.
        self._restored_on_startup: bool = False
        # URL do PR detectado no output (ex: https://github.com/org/repo/pull/42).
        # Persistido durante toda a vida da sessão — uma vez encontrado, não
        # some mesmo após o terminal ser limpo.
        self._pr_url: str | None = None
        # Debounce do refit do xterm.js — durante drag de splitter / resize
        # de janela, evita disparar fits em rajada (cada um dispara 6 fits
        # com timeouts internos no JS → CPU thrash)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(120)
        self._fit_timer.timeout.connect(self._emit_force_fit)

        # Bg do widget inteiro = bg do terminal pra evitar faixa branca
        # entre o toolbar e o terminal (palette default vinha cinza claro
        # em alguns temas).
        self.setStyleSheet(
            "TerminalWidget { background: #0e0e0e; }"
            "QLabel { background: transparent; }"
        )

        # Zera o mínimo de largura do próprio widget — quebra a propagação
        # de minimumSizeHint vinda de filhos (WebEngineView, ctx_bar longo).
        self.setMinimumWidth(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Barra de contexto no topo: mostra os MCPs ativos, os diretórios
        # (cwd + --add-dir) e se a sessão roda num worktree isolado. Fica
        # oculta até `set_context_info` ser chamado (shell puro não tem
        # contexto Claude pra exibir).
        self._ctx_bar = QLabel()
        self._ctx_bar.setObjectName("TerminalContextBar")
        self._ctx_bar.setTextFormat(Qt.TextFormat.RichText)
        self._ctx_bar.setWordWrap(False)
        # Conteúdo variável (MCPs + branch longo) pode ter sizeHint muito
        # largo e propagar mínimo de largura pro centro do dock → janela.
        # Ignorar a dimensão horizontal permite encolher sem forçar scroll.
        self._ctx_bar.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._ctx_bar.setMinimumWidth(0)
        self._ctx_bar.setStyleSheet(
            "QLabel#TerminalContextBar {"
            " background: #141414; color: #9aa0a6;"
            " border-bottom: 1px solid #262626;"
            " padding: 3px 8px; font-size: 11px; }"
        )
        self._ctx_bar.setVisible(False)
        outer.addWidget(self._ctx_bar)

        # Toolbar fica num QWidget próprio pra poder setar bg sem
        # afetar o resto. Sem border-bottom pra não duplicar com a
        # underline azul da tab ativa acima dele.
        toolbar_host = QWidget()
        toolbar_host.setObjectName("TerminalToolbar")
        toolbar_host.setMinimumWidth(0)
        toolbar_host.setStyleSheet(
            "QWidget#TerminalToolbar { background: #0e0e0e; border: 0; }"
        )
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(8, 4, 8, 4)
        self._status = QLabel("(terminal vazio)")
        self._status.setStyleSheet("color: #b0b0b0;")
        # Status pode ser muito longo ("Scampering… 9.1k tokens still thinking
        # with medium effort") — sem Ignored propaga largura mínima enorme pro
        # dock central e dispara scroll horizontal na janela toda.
        self._status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._status.setMinimumWidth(0)
        toolbar.addWidget(self._status)
        toolbar.addStretch()
        # Container invisível: dá parent real aos botões (evita que Qt os
        # trate como top-level e os exiba flutuando) sem afetar o layout
        # do TerminalWidget. setFixedSize(0,0)+hide() garante que o
        # childrenRect() não inflacione o minimumSizeHint.
        _ghost = QWidget(self)
        _ghost.setFixedSize(0, 0)
        _ghost.hide()
        self._continue_btn = QPushButton("▶ Continuar", _ghost)
        self._continue_btn.setEnabled(False)
        self._continue_btn.clicked.connect(self.send_continue)

        self._runners_btn = QPushButton("▤ Runners", _ghost)
        self._runners_btn.setCheckable(True)
        self._runners_btn.clicked.connect(self._on_runners_toggle)

        self._stop_btn = QPushButton("Encerrar", _ghost)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.terminate)

        # Botão ⋯ — abre menu com todas as ações acima.
        self._more_btn = QPushButton("⋯")
        self._more_btn.setToolTip("Ações do console")
        self._more_btn.setFixedWidth(32)
        self._more_btn.clicked.connect(self._open_actions_menu)
        toolbar.addWidget(self._more_btn)
        outer.addWidget(toolbar_host)

        # Banner rosa de PR — aparece quando o Claude cria um PR durante a
        # sessão. Fica entre o toolbar e o xterm, sempre visível enquanto
        # _pr_url estiver definido.
        self._pr_bar = QLabel()
        self._pr_bar.setObjectName("TerminalPrBar")
        self._pr_bar.setTextFormat(Qt.TextFormat.RichText)
        self._pr_bar.setOpenExternalLinks(True)
        self._pr_bar.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._pr_bar.setMinimumWidth(0)
        self._pr_bar.setStyleSheet(
            "QLabel#TerminalPrBar {"
            " background: rgba(244, 114, 182, 0.10);"
            " color: #f472b6;"
            " border-bottom: 1px solid rgba(244, 114, 182, 0.35);"
            " padding: 3px 10px; font-size: 11px; font-weight: 600; }"
        )
        self._pr_bar.setVisible(False)
        outer.addWidget(self._pr_bar)

        self.session = PtySession(self)
        self.session.finished.connect(self._on_session_finished)
        # Repropaga o exit code pra cima. `finished_with_status` é emitido
        # logo depois de `finished` (mesmo evento) — quem só liga em
        # `running_changed`/`finished` continua funcionando, quem precisa
        # do status conecta aqui.
        self.session.finished_with_status.connect(self.session_exited.emit)
        self.session.output_received.connect(self._record_output)

        self.bridge = TerminalBridge(self.session)
        self.bridge.ready.connect(self._on_bridge_ready)

        self.view = QWebEngineView(self)
        self.view.setMinimumWidth(0)
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
        self._main_splitter.setMinimumWidth(0)
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

    def configure_claude(self, cwd: str, resume_id: str | None = None, backend: str = "claude") -> None:
        """Configura o terminal pra resolver sessões do backend ativo.
        O nome ficou 'configure_claude' por compatibilidade mas aceita
        'backend' pra suportar tanto claude quanto opencode."""
        self._backend = backend
        self._claude_cwd = cwd
        self._claude_resume_id = resume_id
        self._claude_start_time = time.time()
        self._session_preview = None
        self._session_resolved = False
        if resume_id is None:
            try:
                from ..claude_sessions import list_sessions_backend
                self._pre_existing_session_ids = {
                    s.id for s in list_sessions_backend(cwd, backend=backend, limit=50)
                }
            except Exception:
                log.debug("snapshot pré-existente falhou", exc_info=True)
                self._pre_existing_session_ids = set()
        else:
            self._pre_existing_session_ids = set()

    def set_context_info(
        self,
        cwd: str,
        extras: list[str] | None = None,
        *,
        worktree_label: str = "",
        is_worktree: bool = False,
        workspace_folders: list[str] | None = None,
    ) -> None:
        """Preenche a barra de contexto no topo do terminal com os MCPs
        ativos, os diretórios da sessão e o estado de worktree.

        MCPs são resolvidos a partir de `workspace_folders` (quando fornecido)
        para mostrar só os MCPs do workspace — mesmo conjunto exibido no top
        bar. Se não fornecido, cai pra `[cwd, *extras]` como antes."""
        from html import escape

        extras = extras or []
        self._extra_dirs = list(extras)
        parts: list[str] = []

        # MCPs: usa workspace_folders pra alinhar com o top bar (evita
        # mostrar MCPs de outros projetos que estejam no cwd da sessão).
        mcp_lookup = workspace_folders if workspace_folders else [cwd, *extras]
        try:
            from ..services.mcp_inspector import list_servers
            names = sorted({s.name for s in list_servers(mcp_lookup)})
        except Exception:
            log.debug("falha ao listar MCPs pro ctx bar", exc_info=True)
            names = []
        if names:
            shown = ", ".join(names[:6])
            if len(names) > 6:
                shown += f" +{len(names) - 6}"
            parts.append(f"🔌 {escape(shown)}")
        else:
            parts.append("🔌 <i>sem MCP</i>")

        # Diretórios: cwd + extras (--add-dir)
        cwd_name = Path(cwd).name or cwd
        dirs = f"📁 {escape(cwd_name)}"
        if extras:
            dirs += f" <span style='color:#7a7f85'>+{len(extras)} dir</span>"
        parts.append(dirs)

        # Worktree / branch
        branch = worktree_label.lstrip(" ·").strip()
        if is_worktree:
            label = f"🌿 worktree: {escape(branch)}" if branch else "🌿 worktree"
            parts.append(f"<span style='color:#7ec699'>{label}</span>")
        elif branch:
            parts.append(f"🌿 {escape(branch)}")

        self._ctx_bar.setText(
            "<span style='color:#5a5f64'>  •  </span>".join(parts)
        )
        # Tooltip com os caminhos completos (o label só mostra o basename)
        tip_dirs = "\n".join([cwd, *extras])
        self._ctx_bar.setToolTip(tip_dirs)
        self._ctx_bar.setVisible(True)

    def effective_title(self) -> str:
        """Título preferido — nome custom (se houver), senão preview da
        sessão truncado, senão _base_title."""
        if self._custom_name:
            text = self._custom_name.strip()
            if len(text) > 60:
                text = text[:59] + "…"
            return text
        if self._session_preview:
            text = self._session_preview.replace("\n", " ").strip()
            if len(text) > 60:
                text = text[:59] + "…"
            return text
        return self.property("_base_title") or ""

    def full_title(self) -> str:
        if self._custom_name:
            return self._custom_name.strip()
        if self._session_preview:
            return self._session_preview.strip()
        return self.property("_base_title") or ""

    def custom_name(self) -> str:
        return self._custom_name

    def set_custom_name(self, name: str) -> None:
        """Define (ou apaga, se `name` vazio) o nome custom desta sessão.
        Persiste em `session_marks.json` por session_id (se já reivindicada)
        e força a UI a re-emitir o título via `activity_changed`, pra que
        a sidebar e as notificações usem o novo nome imediatamente."""
        name = (name or "").strip()
        if name == self._custom_name:
            return
        self._custom_name = name
        sid = self.claimed_session_id()
        if sid:
            try:
                from ..session_marks import set_custom_name as _persist
                _persist(sid, name, self._claude_cwd or "")
            except Exception:
                log.debug("falha ao persistir custom_name", exc_info=True)
        # Re-emite activity pra que TerminalArea propague o novo título.
        self.activity_changed.emit(
            self._last_status, self._last_working, self._last_needs_decision
        )

    def _try_resolve_session(self) -> None:
        if self._session_resolved or not self._claude_cwd:
            return
        backend = getattr(self, "_backend", "claude")
        try:
            from ..claude_sessions import list_sessions_backend
            sessions = list_sessions_backend(self._claude_cwd, backend=backend, limit=20)
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
        # Carrega o custom_name persistido (se houver) — usuário pode ter
        # renomeado essa sessão numa execução anterior do app.
        if not self._custom_name:
            try:
                from ..session_marks import get_custom_name
                saved = get_custom_name(session_id)
                if saved:
                    self._custom_name = saved
            except Exception:
                log.debug("falha ao ler custom_name", exc_info=True)
        elif self._custom_name:
            # Caso o usuário tenha renomeado antes da sessão resolver —
            # agora que sabemos o session_id, persiste retroativamente.
            try:
                from ..session_marks import set_custom_name as _persist
                _persist(session_id, self._custom_name, self._claude_cwd or "")
            except Exception:
                log.debug("falha ao persistir custom_name", exc_info=True)
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

    def extra_dirs(self) -> list[str]:
        """Dirs extras passados via --add-dir (set_context_info). Podem
        ter repos git próprios com PRs/MRs independentes."""
        return list(getattr(self, "_extra_dirs", []))

    def backend(self) -> str:
        return getattr(self, "_backend", "claude")

    def claimed_session_path(self) -> Path | None:
        """Caminho da sessão atualmente vinculada. Pra opencode retorna
        o path da DB (usado como sentinela de existência)."""
        sid = self.claimed_session_id()
        if not sid or not self._claude_cwd:
            return None
        backend = getattr(self, "_backend", "claude")
        if backend == "opencode":
            from ..opencode_sessions import OPCODE_DB_PATH
            return OPCODE_DB_PATH if OPCODE_DB_PATH.exists() else None
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

        # Hold needs_decision: uma vez que o permission prompt é detectado,
        # mantém needs_decision=True até Claude voltar a trabalhar (usuário
        # respondeu). O buffer do TUI re-renderiza constantemente e pode fazer
        # _has_decision_prompt oscilar True→False sem que o prompt tenha sumido
        # de verdade — sem o hold, a sidebar volta pra "Ocioso" em milissegundos.
        if activity.needs_decision:
            self._needs_decision_held = True
        elif activity.is_working:
            self._needs_decision_held = False
        effective_needs_decision = self._needs_decision_held and not activity.is_working

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
            and not effective_needs_decision
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

        # Plan mode: só atualiza o flag quando idle (footer de modo visível).
        # Durante working, o footer some — mantém o último valor conhecido.
        if not activity.is_working:
            self._is_plan_mode = activity.is_plan_mode

        if (
            activity.status != self._last_status
            or activity.is_working != self._last_working
            or effective_needs_decision != self._last_needs_decision
        ):
            self._last_status = activity.status
            self._last_working = activity.is_working
            self._last_needs_decision = effective_needs_decision
            self.activity_changed.emit(
                activity.status, activity.is_working, effective_needs_decision
            )
            self._refresh_continue_visibility()

        # Detecção de PR: escaneia o buffer inteiro (não só a última linha)
        # pra capturar a URL mesmo que ela tenha rolado para fora das 8k.
        if self._pr_url is None:
            from ..services.runner_url_detect import detect_pr_url
            buf_text = bytes(self._output_buffer).decode("utf-8", errors="replace")
            pr = detect_pr_url(buf_text)
            if pr:
                self._pr_url = pr
                self._show_pr_banner(pr)
                self.pr_detected.emit(pr)

    def set_detected_pr_url(self, url: str) -> None:
        """Injeta URL de PR detectado externamente (PrStatusPoller).
        Idempotente — não re-emite se a URL já é a mesma."""
        if not url or url == self._pr_url:
            return
        self._pr_url = url
        self._show_pr_banner(url)
        self.pr_detected.emit(url)

    def _show_pr_banner(self, url: str) -> None:
        from ..services.runner_url_detect import pr_number_from_url
        from html import escape
        num = pr_number_from_url(url)
        label = f"PR #{num}" if num else "Pull Request"
        safe_url = escape(url)
        self._pr_bar.setText(
            f"⬡ PR criado: "
            f"<a href='{safe_url}' style='color:#f472b6; text-decoration:underline;'>"
            f"{label}</a>"
        )
        self._pr_bar.setVisible(True)

    @property
    def is_plan_mode(self) -> bool:
        return self._is_plan_mode

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
        self.session.write(text.encode("utf-8"))
        if submit:
            # Why: Claude CLI usa bracketed paste — texto + '\r' na mesma
            # escrita vira paste com newline (não submete). Mandar o '\r'
            # numa escrita separada, depois de um tick, faz a TUI tratar
            # como Enter de verdade.
            QTimer.singleShot(
                120,
                lambda: self.session.is_running()
                and self.session.write(b"\r"),
            )

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
        """Atualiza o estado 'Continuar disponível' (sessão restaurada+ociosa).
        O botão em si nunca fica visível — foi removido da toolbar; o estado
        é consultado pelo menu ⋯ via `continue_available`. Sem isso o botão
        (parentless, fora de qualquer layout) aparecia flutuando sobre a janela."""
        idle = (
            self._is_running
            and not self._last_working
            and not self._last_needs_decision
        )
        self._continue_available = self._restored_on_startup and idle
        # Nunca mostra o botão diretamente — ele não está em nenhum layout e
        # setVisible(True) num widget parentless o faz flutuar sobre a UI.
        self._continue_btn.setVisible(False)

    def _open_actions_menu(self) -> None:
        """Abre QMenu com todas as ações do console (▶ Continuar, ⚙ Modo,
        ▤ Runners, Encerrar) ancorado abaixo do botão ⋯."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1f1f1f; color: #e6e6e6; "
            "border: 1px solid #2c2c2c; border-radius: 6px; }"
            "QMenu::item { padding: 6px 16px; }"
            "QMenu::item:selected { background: #3d6ea8; color: #fff; }"
            "QMenu::item:disabled { color: #555; }"
            "QMenu::separator { height: 1px; background: #2a2a2a; margin: 3px 8px; }"
        )

        act_continue = menu.addAction("▶  Continuar")
        act_continue.setEnabled(getattr(self, "_continue_available", False))
        act_continue.triggered.connect(self.send_continue)

        runners_checked = self._runners_btn.isChecked()
        act_runners = menu.addAction(
            "▤  Runners  ✓" if runners_checked else "▤  Runners"
        )
        act_runners.triggered.connect(self._on_runners_toggle)

        menu.addSeparator()

        act_stop = menu.addAction("⏹  Encerrar")
        act_stop.setEnabled(self._stop_btn.isEnabled())
        act_stop.triggered.connect(self.terminate)

        pos = self._more_btn.mapToGlobal(self._more_btn.rect().bottomRight())
        pos.setX(pos.x() - menu.sizeHint().width())
        pos.setY(pos.y() + 4)
        menu.exec(pos)

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
