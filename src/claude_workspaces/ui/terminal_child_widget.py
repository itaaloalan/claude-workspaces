"""Widget custom pros children da sidebar tree — mostra o estado de um
console do Claude rodando num workspace, no estilo IntelliJ:

    [icon]  Console #N — claude       [▶] [⚙]   ← ações inline (toggle via header)
            Trabalhando · última ação do Claude
"""

import time
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

# Estados visíveis na UI — labels padronizados de acordo com o pedido
# do usuário (Trabalhando/Aguardando/Ocioso/Erro/Concluído).
STATE_WORKING = "working"      # rodando (trabalhando)
STATE_AWAITING = "awaiting"    # aguardando decisão (permission prompt)
STATE_IDLE = "idle"            # parado no prompt principal (sem ação ativa)
STATE_DONE = "done"            # concluído sem erro
STATE_ERROR = "error"          # processo falhou / saiu com erro


STATE_LABEL = {
    STATE_WORKING: "Trabalhando",
    STATE_AWAITING: "Aguardando",
    STATE_IDLE: "Ocioso",
    STATE_DONE: "Concluído",
    STATE_ERROR: "Erro",
}

# Cor do título do console por estado — pra dar um sinal extra de
# "tem trabalho rolando aqui" só batendo o olho na lista. Idle/Done
# ficam num cinza mais discreto pra contrastar com os ativos.
STATE_TITLE_COLOR = {
    STATE_WORKING: theme.WARNING,
    STATE_AWAITING: theme.WAITING,
    STATE_IDLE: theme.TEXT_FAINT,
    STATE_DONE: theme.TEXT_PRIMARY,
    STATE_ERROR: theme.DANGER,
}

STATE_COLOR = {
    # Trabalhando = amber (trabalho em curso)
    STATE_WORKING: theme.WARNING,
    # Aguardando = laranja forte (decisão pendente)
    STATE_AWAITING: theme.WAITING,
    # Ocioso = vermelho (chamativo — Claude esperando ação do user)
    STATE_IDLE: theme.DANGER,
    # Concluído = verde
    STATE_DONE: theme.SUCCESS,
    # Erro = vermelho
    STATE_ERROR: theme.DANGER,
}

_CHIP_MODEL_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_LINK};"
    f"  background: transparent;"
    f"  border: 0;"
    f"  padding: 0px 4px 0px 0px;"
    f"  font-size: 10px;"
    f"}}"
)

_CHIP_BRANCH_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_FAINT};"
    f"  background: transparent;"
    f"  border: 0;"
    f"  padding: 0px 4px;"
    f"  font-size: 10px;"
    f"}}"
)

_INLINE_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: 4px;"
    f"  padding: 0px 4px;"
    f"  font-size: 12px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
    f"QPushButton:disabled {{"
    f"  color: {theme.TEXT_DISABLED};"
    f"}}"
)


class TerminalChildWidget(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        # Tamanho previsível pra não brigar com o QTreeWidget no resize
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # 2 linhas: título+ações / estado+modelo+branch. Quem define a
        # altura efetiva do row no QTreeWidget é o setSizeHint no
        # `_CHILD_HEIGHT` lá no main_window — manter sincronizado
        # (row = widget + 8px de border+padding do item).
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 0, 4, 0)
        outer.setSpacing(4)

        # Seleção: em vez de barra vertical à esquerda, usa um tint
        # sutil no bg do widget inteiro (set_selected pinta um RGBA
        # discreto). Estado continua sinalizado pelo texto colorido em
        # _state_label ("Trabalhando · …" em âmbar) + status bar global.
        # Mantemos os atributos pra preservar API (`set_selected` etc),
        # mas eles ficam escondidos / com width 0.
        self._selection_strip = QFrame()
        self._selection_strip.setVisible(False)
        self._status_strip = QFrame()
        self._status_strip.setVisible(False)
        # Auto-render: setAutoFillBackground pra QSS pegar no widget pai.
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            "TerminalChildWidget { background: transparent; border-radius: 4px; }"
        )

        # Coluna do ícone (spinner ‖/⠋) foi removida do layout — a faixa
        # vertical de estado (`_status_strip`) já cumpre o papel de mostrar
        # o estado do console em um glance, sem duplicar o sinal. O QLabel
        # continua existindo (escondido) pra manter compatibilidade com
        # `update_state` que ainda chama `setText` nele.
        self._icon = QLabel()
        self._icon.setVisible(False)

        # Ícone do Claude (robot) à esquerda — sinaliza "este card é uma
        # sessão Claude" e dá feedback visual de seleção (azul quando
        # selecionado, cinza nos demais).
        from .icons import ic as _ic
        self._claude_icon = QLabel()
        self._claude_icon.setFixedSize(16, 16)
        self._claude_icon_unselected_pix = _ic(
            "fa5s.robot", color=theme.TEXT_FAINT
        ).pixmap(14, 14)
        self._claude_icon_selected_pix = _ic(
            "fa5s.robot", color=theme.PRIMARY_HOVER
        ).pixmap(14, 14)
        self._claude_icon.setPixmap(self._claude_icon_unselected_pix)
        self._claude_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(
            self._claude_icon, 0, Qt.AlignmentFlag.AlignVCenter
        )

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Title row: título + ações inline (✏ ▶ ⚙ ✖) à direita.
        # Visibilidade das ações controlada pelo toggle no header
        # WORKSPACES (set_actions_visible). Callbacks são injetadas
        # pelo MainWindow via set_action_callbacks.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"color: {STATE_TITLE_COLOR[STATE_IDLE]};"
            f" font-weight: 600; font-size: 12px;"
        )
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(False)
        self._title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._title_label.setMaximumHeight(16)
        title_row.addWidget(self._title_label, stretch=1)

        # Badge de notificações pendentes (pintado pelo MainWindow via
        # NotificationService.unread_by_session — chave: claimed_session_id).
        self._notif_badge = QLabel("")
        self._notif_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notif_badge.setStyleSheet(
            "QLabel {"
            "  background: rgba(201, 119, 45, 100);"
            "  color: #ffce99;"
            "  font-size: 9px; font-weight: 700;"
            "  padding: 1px 5px; border-radius: 6px;"
            "}"
        )
        self._notif_badge.setToolTip("Notificações pendentes nesta sessão")
        self._notif_badge.hide()
        title_row.addWidget(self._notif_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Estado atual + elegibilidade pro ▶ continuar. O continue só faz
        # sentido em sessões restauradas no startup (--resume) que estão
        # ociosas — caso típico: app fechou no meio de uma tarefa e o
        # Claude voltou parado no prompt. Em todo outro estado o botão é
        # ruído visual (ou está rodando, ou aguardando decisão, ou é uma
        # sessão fresca que não tem nada pra continuar).
        self._current_state: str = STATE_IDLE
        self._continue_eligible: bool = False
        self._actions_user_visible: bool = True
        # Timestamp em que entrou em STATE_IDLE — usado pra exibir
        # "Ocioso · 2m 30s" na sidebar. Resetado a cada transição
        # de estado; quando volta pra idle, recomeça do zero.
        self._idle_since: float | None = None
        # Flag de pisca-pisca do estado AWAITING — alterna a cada
        # tick_awaiting() pra chamar atenção visual quando Claude
        # pede decisão. Resetado fora do estado awaiting.
        self._awaiting_blink_on: bool = False
        # Última ação reportada (statusline do Claude). Concatenada
        # no _state_label como "Trabalhando · …" pra economizar
        # uma linha do card na sidebar.
        self._last_action: str = ""
        # Snapshot duplicado dos dados que o footer global também
        # consome — guardados em campos próprios pra `status_info()`
        # poder devolver sem reparsear o QLabel.
        self._model: str = ""
        self._branch: str = ""
        self._modified: int = 0

        # Bloco de ações fica na própria title row, à direita do título —
        # mantém o título com peso visual (bold) e libera a linha do estado
        # pra ser uma faixa fina só de texto.
        self._actions_widget = QWidget()
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(0)

        # Botão Renomear (✏) removido do layout inline pra reduzir poluição
        # visual — ação continua disponível via clique direito → "Renomear
        # sessão…" no menu de contexto. Widget mantido (escondido) pra
        # preservar a API de _wire_child_actions/disconnects.
        self._rename_btn = QPushButton("✏")
        self._rename_btn.setVisible(False)

        self._continue_btn = QPushButton("▶")
        self._continue_btn.setFixedSize(20, 18)
        self._continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue_btn.setStyleSheet(_INLINE_BTN_QSS)
        self._continue_btn.setToolTip(
            "Continuar este console — manda 'continue' + Enter pro Claude"
        )
        self._continue_btn.setEnabled(False)
        self._continue_btn.setVisible(False)
        actions_layout.addWidget(self._continue_btn)

        self._mode_btn = QPushButton("⚙")
        self._mode_btn.setFixedSize(20, 18)
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setStyleSheet(_INLINE_BTN_QSS)
        self._mode_btn.setToolTip(
            "Modo / effort / modelo — abre popup com Plan/Auto/Default,"
            " /effort e /model"
        )
        self._mode_btn.setEnabled(False)
        actions_layout.addWidget(self._mode_btn)

        # ✖ Encerrar/remover console — mesmo atalho que estava só no menu
        # de contexto (clique direito). Hover em vermelho pra deixar claro
        # que é destrutivo.
        self._close_btn = QPushButton("✖")
        self._close_btn.setFixedSize(20, 18)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  color: {theme.TEXT_FAINT};"
            f"  border: 0;"
            f"  border-radius: 4px;"
            f"  padding: 0px 4px;"
            f"  font-size: 12px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {theme.BG_SURFACE};"
            f"  color: {theme.DANGER};"
            f"}}"
            f"QPushButton:disabled {{"
            f"  color: {theme.TEXT_DISABLED};"
            f"}}"
        )
        self._close_btn.setToolTip(
            "Encerrar/remover console — encerra o processo (se rodando)"
            " e remove esta aba"
        )
        actions_layout.addWidget(self._close_btn)

        title_row.addWidget(
            self._actions_widget,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        vbox.addLayout(title_row)

        # 2a linha: estado à esquerda, chips de modelo + branch à direita.
        # Antes eram 3 linhas (título / estado / modelo+branch) — agora 2,
        # com modelo/branch alinhados pela direita na mesma row do estado.
        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(6)

        self._state_label = QLabel(STATE_LABEL[STATE_IDLE])
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[STATE_IDLE]};"
            f" font-size: 10px;"
            f" letter-spacing: 0.3px;"
        )
        self._state_label.setWordWrap(False)
        self._state_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._state_label.setMaximumHeight(16)
        state_row.addWidget(self._state_label, stretch=1)

        self._session_label = QLabel("")
        self._session_label.setTextFormat(Qt.TextFormat.RichText)
        self._session_label.setStyleSheet(_CHIP_MODEL_QSS)
        self._session_label.setWordWrap(False)
        self._session_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._session_label.setMaximumHeight(16)
        self._session_label.setVisible(False)
        state_row.addWidget(self._session_label, 0, Qt.AlignmentFlag.AlignRight)

        self._git_label = QLabel("")
        self._git_label.setTextFormat(Qt.TextFormat.RichText)
        self._git_label.setStyleSheet(_CHIP_BRANCH_QSS)
        self._git_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._git_label.setMaximumHeight(16)
        self._git_label.setVisible(False)
        state_row.addWidget(self._git_label, 0, Qt.AlignmentFlag.AlignRight)

        vbox.addLayout(state_row)

        outer.addLayout(vbox, stretch=1)

    def set_unread_count(self, count: int) -> None:
        """Pinta badge laranja com nº de notificações pendentes nessa sessão."""
        if count <= 0:
            self._notif_badge.hide()
            return
        self._notif_badge.setText(str(count) if count < 100 else "99+")
        self._notif_badge.show()

    def set_title(self, title: str, tooltip: str = "") -> None:
        if title:
            self._title = title
            self._title_label.setText(self._elide(title))
        self.setToolTip(tooltip or title or self._title)

    def _elide(self, text: str) -> str:
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._title_label.font())
        width = self._title_label.width() or 200
        return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._title:
            self._title_label.setText(self._elide(self._title))

    def update_state(
        self,
        state: str,
        last_action: str,
        spinner_char: str = "⠋",
    ) -> None:
        if state == STATE_WORKING:
            self._icon.setText(spinner_char)
            icon_size = 12
        elif state == STATE_AWAITING:
            self._icon.setText("!")
            icon_size = 12
        elif state == STATE_IDLE:
            # `❚❚` é bem encorpado — reduz a fonte pra não dominar a row
            self._icon.setText("‖")
            icon_size = 11
        else:
            self._icon.setText("✓")
            icon_size = 12
        self._icon.setStyleSheet(
            f"color: {STATE_COLOR[state]}; font-family: monospace;"
            f" font-size: {icon_size}px;"
        )
        self._status_strip.setStyleSheet(
            f"background: {STATE_COLOR[state]}; border: 0;"
        )
        # Entrou agora em idle? marca o instante pra começar a contar.
        # Saiu de idle? zera. Reentrar em idle reinicia o cronômetro.
        if state == STATE_IDLE:
            if self._current_state != STATE_IDLE or self._idle_since is None:
                self._idle_since = time.monotonic()
        else:
            self._idle_since = None
        self._state_label.setText(self._compose_state_text(state))
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[state]};"
            f" font-size: 10px;"
            f" letter-spacing: 0.3px;"
        )
        if last_action:
            self._last_action = last_action if len(last_action) <= 55 else last_action[:54] + "…"
        else:
            self._last_action = ""
        self._state_label.setText(self._compose_state_text(state))
        # Tinta o título com a cor do estado pra dar leitura rápida da
        # lista — sessões trabalhando ficam âmbar, aguardando laranja,
        # ociosas em cinza desbotado.
        self._title_label.setStyleSheet(
            f"color: {STATE_TITLE_COLOR[state]};"
            f" font-weight: 600; font-size: 12px;"
        )
        # Memoriza estado e reavalia visibilidade do ▶ — ele só aparece
        # em sessão restaurada+ociosa.
        self._current_state = state
        self._refresh_continue_visibility()

    def _compose_state_text(self, state: str) -> str:
        base = STATE_LABEL[state]
        if state == STATE_IDLE and self._idle_since is not None:
            elapsed = int(time.monotonic() - self._idle_since)
            if elapsed >= 1:
                base = f"{base} · {_fmt_elapsed(elapsed)}"
        if self._last_action:
            return f"{base} · {self._last_action}"
        return base

    def tick_idle(self) -> None:
        """Re-renderiza o label de estado quando ocioso pra atualizar o
        cronômetro 'Ocioso · 2m 30s'. Chamado por um QTimer no MainWindow
        a cada segundo enquanto houver consoles ociosos."""
        if self._current_state != STATE_IDLE or self._idle_since is None:
            return
        self._state_label.setText(self._compose_state_text(STATE_IDLE))

    def tick_awaiting(self) -> None:
        """Pisca o label 'Aguardando' alternando entre laranja (WAITING)
        e branco (TEXT_BRIGHT) a cada chamada. Chamado pelo mesmo timer
        de 1s do tick_idle no MainWindow. Sai do estado awaiting reseta
        a cor e o flag — próxima entrada começa do zero."""
        if self._current_state != STATE_AWAITING:
            if self._awaiting_blink_on:
                self._awaiting_blink_on = False
            return
        self._awaiting_blink_on = not self._awaiting_blink_on
        color = theme.TEXT_BRIGHT if self._awaiting_blink_on else theme.WAITING
        self._state_label.setStyleSheet(
            f"color: {color};"
            f" font-size: 10px;"
            f" letter-spacing: 0.3px;"
        )

    def set_action_callbacks(
        self,
        on_continue: Callable[[], None],
        on_open_mode_popup: Callable[[QWidget], None],
        on_close: Callable[[], None] | None = None,
        on_rename: Callable[[], None] | None = None,
    ) -> None:
        """Conecta os cliques dos botões inline (✏ ▶ ⚙ ✖). `on_open_mode_popup`
        recebe o próprio botão como anchor pra posicionar o ModePopup."""
        # Desconecta primeiro pra evitar duplicar handlers ao reconectar
        try:
            self._continue_btn.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            self._mode_btn.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            self._close_btn.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            self._rename_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._continue_btn.clicked.connect(lambda _=False: on_continue())
        self._mode_btn.clicked.connect(
            lambda _=False, b=self._mode_btn: on_open_mode_popup(b)
        )
        if on_close is not None:
            self._close_btn.clicked.connect(lambda _=False: on_close())
        if on_rename is not None:
            self._rename_btn.clicked.connect(lambda _=False: on_rename())

    def set_selected(self, selected: bool) -> None:
        """Pinta o background do card com tint discreto quando selecionado.
        Sem barras laterais (anteriormente _selection_strip + _status_strip)
        pra reduzir poluição visual da sidebar. Estado do console continua
        sinalizado pelo texto colorido em `_state_label` + status bar global."""
        if selected:
            self.setStyleSheet(
                "TerminalChildWidget { background: rgba(61, 110, 168, 38); "
                "border-radius: 4px; border-left: 2px solid #3d6ea8; }"
            )
            self._claude_icon.setPixmap(self._claude_icon_selected_pix)
        else:
            self.setStyleSheet(
                "TerminalChildWidget { background: transparent; border-radius: 4px; }"
            )
            self._claude_icon.setPixmap(self._claude_icon_unselected_pix)

    def set_actions_visible(self, visible: bool) -> None:
        """Mostra/esconde o bloco de ações inline (▶ ⚙) via toggle do
        header WORKSPACES. Quando oculto, o espaço é colapsado mas a
        altura total da row continua intacta."""
        self._actions_user_visible = visible
        self._actions_widget.setVisible(visible)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Habilita/desabilita os botões conforme o terminal está rodando.
        O ✖ fica sempre habilitado — faz sentido remover mesmo console
        já encerrado (limpa a sidebar)."""
        self._continue_btn.setEnabled(enabled)
        self._mode_btn.setEnabled(enabled)
        self._refresh_continue_visibility()

    def set_continue_eligible(self, eligible: bool) -> None:
        """Marca se este console pode exibir o ▶ continuar — verdadeiro
        só pra sessões restauradas no startup (`--resume`). Sessões
        novas/iniciadas no app não têm o que continuar, então o botão
        não aparece e o usuário não fica confuso clicando à toa."""
        self._continue_eligible = eligible
        self._refresh_continue_visibility()

    def _refresh_continue_visibility(self) -> None:
        """Esconde o ▶ a menos que a sessão seja restaurada+ociosa. ⚙
        segue o toggle do header (set_actions_visible) — não filtramos
        ele por estado."""
        should_show = (
            self._continue_eligible
            and self._current_state == STATE_IDLE
        )
        self._continue_btn.setVisible(should_show)

    def update_git_info(self, branch: str, modified: int) -> None:
        """Atualiza o label do lado direito com branch e contagem de
        arquivos modificados (working tree + staged + untracked).
        `branch` vazio = pasta não é repo git → esconde o label.
        """
        self._branch = branch
        self._modified = modified
        if not branch:
            self._git_label.setVisible(False)
            self._git_label.setText("")
            return
        # Encurta nomes longos pra não dominar a row do chip
        b = branch if len(branch) <= 18 else branch[:17] + "…"
        if modified > 0:
            self._git_label.setText(
                f"⎇ {b}  <span style='color: {theme.WARNING};'>●{modified}</span>"
            )
            tip = f"Branch: {branch} — {modified} arquivo(s) modificado(s)"
        else:
            self._git_label.setText(f"⎇ {b}")
            tip = f"Branch: {branch} — working tree limpo"
        self._git_label.setToolTip(tip)
        self._git_label.setVisible(True)

    def update_session_info(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
        context_tokens: int = 0,
        context_window: int = 0,
    ) -> None:
        """Atualiza a 3a linha com apenas o modelo encurtado
        (claude-opus-4-7 → opus-4-7). Os números de ctx/in/out/cache que
        antes apareciam aqui estavam errados na prática — custo e detalhes
        continuam no menu de contexto."""
        self._model = model or ""
        if not model:
            self._session_label.setVisible(False)
            self._session_label.setText("")
            return
        model_short = _shorten_model(model)
        self._session_label.setText(model_short)
        self._session_label.setToolTip(f"Modelo: {model}")
        self._session_label.setVisible(True)

    def status_info(self) -> dict:
        """Snapshot do estado dinâmico exposto na sidebar — consumido
        pelo footer global pra refletir o console selecionado.
        """
        return {
            "state": self._current_state,
            "state_text": self._compose_state_text(self._current_state),
            "state_color": STATE_COLOR[self._current_state],
            "model": _shorten_model(self._model) if self._model else "",
            "model_full": self._model,
            "branch": self._branch,
            "modified": self._modified,
            "title": self._title,
        }


def _shorten_model(model: str) -> str:
    """`claude-opus-4-7` → `opus-4-7`. Mantém sufixos como `[1m]`."""
    if model.startswith("claude-"):
        return model[len("claude-"):]
    return model


def _fmt_elapsed(seconds: int) -> str:
    """Formata segundos como `45s`, `2m 30s`, `1h 05m` — compacto pra
    caber na sidebar sem empurrar os outros labels da row."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m"


