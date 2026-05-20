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

# Estados visíveis na UI
STATE_WORKING = "working"
STATE_AWAITING = "awaiting"  # Claude pediu decisão (permission prompt)
STATE_IDLE = "idle"          # Claude terminou turno, no prompt principal
STATE_DONE = "done"


STATE_LABEL = {
    STATE_WORKING: "Trabalhando",
    STATE_AWAITING: "Aguardando",
    STATE_IDLE: "Ocioso",
    STATE_DONE: "Concluído",
}

STATE_COLOR = {
    STATE_WORKING: theme.WARNING,
    STATE_AWAITING: theme.WAITING,
    STATE_IDLE: theme.DANGER,
    STATE_DONE: theme.SUCCESS,
}

_CHIP_MODEL_QSS = (
    f"QLabel {{"
    f"  color: {theme.TEXT_LINK};"
    f"  background: transparent;"
    f"  border: 0;"
    f"  padding: 0px 4px 0px 0px;"
    f"  font-size: 10px;"
    f"  font-weight: 600;"
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
        # Altura aumentada pra caber a 3a linha (chips de modelo+branch).
        # Quem define a altura efetiva do row no QTreeWidget é o
        # setSizeHint no `_CHILD_HEIGHT` lá no main_window — manter
        # sincronizado (row = widget + 12px de border+padding do item).
        self.setMinimumHeight(74)
        self.setMaximumHeight(74)

        outer = QHBoxLayout(self)
        # 2px de margem à esquerda pra que o `_status_strip` (3px) fique
        # dentro da borda 1px do QTreeWidget::item — sem isso o strip
        # encosta no canto e visualmente "fura" o card.
        outer.setContentsMargins(2, 2, 4, 2)
        outer.setSpacing(6)

        # Faixa vertical 3px no canto esquerdo do row, pintada com a cor do
        # estado atual (ocioso=vermelho, trabalhando=âmbar, aguardando=laranja,
        # concluído=verde). Substitui a "linha de seleção" monocromática por
        # uma pista visual permanente do estado de cada console.
        self._status_strip = QFrame()
        self._status_strip.setFixedWidth(3)
        self._status_strip.setStyleSheet(
            f"background: {STATE_COLOR[STATE_IDLE]}; border: 0;"
        )
        outer.addWidget(self._status_strip)

        # Barra branca de seleção — fica encostada do lado direito do
        # `_status_strip`, mesma altura, escondida por padrão. O
        # `MainWindow._on_selection_changed` chama `set_selected(bool)`
        # pra mostrar/esconder. É a única pista visual de "este é o
        # console selecionado" — o bg do row é transparente.
        self._selection_strip = QFrame()
        self._selection_strip.setFixedWidth(2)
        self._selection_strip.setStyleSheet(
            "background: #ffffff; border: 0;"
        )
        self._selection_strip.setVisible(False)
        outer.addWidget(self._selection_strip)

        # Coluna do ícone (spinner ‖/⠋) foi removida do layout — a faixa
        # vertical de estado (`_status_strip`) já cumpre o papel de mostrar
        # o estado do console em um glance, sem duplicar o sinal. O QLabel
        # continua existindo (escondido) pra manter compatibilidade com
        # `update_state` que ainda chama `setText` nele.
        self._icon = QLabel()
        self._icon.setVisible(False)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(1)

        # Title row: título + ações inline (▶ Continuar, ⚙ Modo).
        # Ações ficam à direita; visibilidade controlada pelo toggle no
        # header WORKSPACES (set_actions_visible). Callbacks são injetadas
        # pelo MainWindow via set_action_callbacks.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-weight: 600; font-size: 12px;"
        )
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(False)
        self._title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._title_label.setMaximumHeight(16)
        title_row.addWidget(self._title_label, stretch=1)
        vbox.addLayout(title_row)

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

        # Bloco de ações vai à direita da row, vertical-center alinhado
        # com a branch — mais coerente do que ficar grudado no título.
        self._actions_widget = QWidget()
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(2)

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

        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_row.setSpacing(6)

        self._state_label = QLabel(STATE_LABEL[STATE_IDLE])
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[STATE_IDLE]};"
            f" font-size: 10px; font-weight: 600;"
            f" letter-spacing: 0.3px;"
        )
        self._state_label.setWordWrap(False)
        self._state_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._state_label.setMaximumHeight(14)
        sub_row.addWidget(self._state_label)
        # Empurra as ações inline pro lado direito da MESMA linha do
        # estado ("Ocioso · …"). Sem esse stretch o estado ficava
        # centralizado no row porque era o único item flutuante.
        sub_row.addStretch(1)
        sub_row.addWidget(
            self._actions_widget,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )

        vbox.addLayout(sub_row)

        # Linha dedicada à "última ação" (ex.: texto da statusline do
        # Claude — "Context ▓▓▓ 7% · Usage …"). Antes vinha na mesma
        # linha do "Ocioso · 12m 15s", o que poluía o estado quando a
        # statusline era longa. Agora fica numa linha própria entre o
        # estado e o modelo.
        self._action_label = QLabel("")
        self._action_label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px;"
            f" font-family: monospace;"
        )
        self._action_label.setWordWrap(False)
        self._action_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._action_label.setMaximumHeight(14)
        vbox.addWidget(self._action_label)

        # 3a linha: chip do modelo + chip da branch lado a lado.
        # Antes a branch ficava num label solto vertical-centered no canto
        # direito do card (desalinhada com o modelo). Agora os dois são
        # chips na mesma row pra leitura linear.
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(4)

        self._session_label = QLabel("")
        self._session_label.setTextFormat(Qt.TextFormat.RichText)
        self._session_label.setStyleSheet(_CHIP_MODEL_QSS)
        self._session_label.setWordWrap(False)
        self._session_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._session_label.setMaximumHeight(16)
        self._session_label.setVisible(False)
        model_row.addWidget(self._session_label)

        self._git_label = QLabel("")
        self._git_label.setTextFormat(Qt.TextFormat.RichText)
        self._git_label.setStyleSheet(_CHIP_BRANCH_QSS)
        self._git_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._git_label.setMaximumHeight(16)
        self._git_label.setVisible(False)
        model_row.addWidget(self._git_label)
        model_row.addStretch(1)

        vbox.addLayout(model_row)

        outer.addLayout(vbox, stretch=1)

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
            f" font-size: 10px; font-weight: 600;"
            f" letter-spacing: 0.3px;"
        )
        if last_action:
            shown = last_action if len(last_action) <= 55 else last_action[:54] + "…"
            self._action_label.setText(shown)
            self._action_label.setVisible(True)
        else:
            self._action_label.setVisible(False)
        # Memoriza estado e reavalia visibilidade do ▶ — ele só aparece
        # em sessão restaurada+ociosa.
        self._current_state = state
        self._refresh_continue_visibility()

    def _compose_state_text(self, state: str) -> str:
        base = STATE_LABEL[state]
        if state == STATE_IDLE and self._idle_since is not None:
            elapsed = int(time.monotonic() - self._idle_since)
            if elapsed >= 1:
                return f"{base} · {_fmt_elapsed(elapsed)}"
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
            f" font-size: 10px; font-weight: 600;"
            f" letter-spacing: 0.3px;"
        )

    def set_action_callbacks(
        self,
        on_continue: Callable[[], None],
        on_open_mode_popup: Callable[[QWidget], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        """Conecta os cliques dos botões inline (▶ ⚙ ✖). `on_open_mode_popup`
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
        self._continue_btn.clicked.connect(lambda _=False: on_continue())
        self._mode_btn.clicked.connect(
            lambda _=False, b=self._mode_btn: on_open_mode_popup(b)
        )
        if on_close is not None:
            self._close_btn.clicked.connect(lambda _=False: on_close())

    def set_selected(self, selected: bool) -> None:
        """Mostra/esconde a barra branca de seleção encostada do lado
        direito do `_status_strip`. Chamado pelo MainWindow quando o
        item da tree muda de seleção."""
        self._selection_strip.setVisible(selected)

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
        if not model:
            self._session_label.setVisible(False)
            self._session_label.setText("")
            return
        model_short = _shorten_model(model)
        self._session_label.setText(model_short)
        self._session_label.setToolTip(f"Modelo: {model}")
        self._session_label.setVisible(True)


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


