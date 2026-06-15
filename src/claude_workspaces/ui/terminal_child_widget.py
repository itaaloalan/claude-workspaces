"""Widget custom pros children da sidebar tree — mostra o estado de um
console do Claude rodando num workspace, no estilo card moderno:

    ┃ [icon]  #2 oi                          [▶] [⋯]
    ┃         ⏸ Aguardando permissão
    ┃         opus-4.7  ·  italo/branch  ·  2K
"""

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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
from .text_utils import _strip_noise  # noqa: F401

# Estados visíveis na UI — labels padronizados de acordo com o pedido
# do usuário (Trabalhando/Aguardando/Ocioso/Erro/Concluído).
STATE_WORKING = "working"      # rodando (trabalhando)
STATE_PLANNING = "planning"    # trabalhando em plan mode
STATE_AWAITING = "awaiting"    # aguardando decisão (permission prompt)
STATE_IDLE = "idle"            # parado no prompt principal (sem ação ativa)
STATE_DONE = "done"            # concluído sem erro
STATE_ERROR = "error"          # processo falhou / saiu com erro


STATE_LABEL = {
    STATE_WORKING: "Trabalhando",
    STATE_PLANNING: "Planejando",
    STATE_AWAITING: "Aguardando decisão",
    STATE_IDLE: "Ocioso",
    STATE_DONE: "Concluído",
    STATE_ERROR: "Erro",
}

# Título sempre em branco/claro (TEXT_PRIMARY) — estado é sinalizado
# pela barra lateral colorida + linha de estado abaixo. Mantemos a
# constante pra compat, mas todos os valores apontam pra TEXT_PRIMARY
# (callers existentes não quebram).
STATE_TITLE_COLOR = {
    STATE_WORKING: theme.TEXT_PRIMARY,
    STATE_PLANNING: theme.TEXT_PRIMARY,
    STATE_AWAITING: theme.TEXT_PRIMARY,
    STATE_IDLE: theme.TEXT_PRIMARY,
    STATE_DONE: theme.TEXT_PRIMARY,
    STATE_ERROR: theme.TEXT_PRIMARY,
}

STATE_COLOR = {
    # Trabalhando = amber (trabalho em curso)
    STATE_WORKING: theme.WARNING,
    # Planejando = teal (plan mode ativo)
    STATE_PLANNING: theme.PLANNING,
    # Aguardando = laranja forte (decisão pendente)
    STATE_AWAITING: theme.WAITING,
    # Ocioso = cinza. Vermelho fica reservado para erro; assim a lista não
    # parece estar cheia de falhas quando só há sessões paradas no prompt.
    STATE_IDLE: theme.TEXT_FAINT,
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
    # Clique no chip de modificados (●N) — MainWindow foca o console e
    # abre o painel Git do dock direito.
    open_git_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        # Tamanho previsível pra não brigar com o QTreeWidget no resize
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # 2 linhas: título+ações / estado+modelo+branch. Quem define a
        # altura efetiva do row no QTreeWidget é o setSizeHint no
        # `_CHILD_HEIGHT` lá no main_window — manter sincronizado
        # (row = widget + 8px de border+padding do item).
        self.setMinimumHeight(38)
        self.setMaximumHeight(38)

        wrapper = QHBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)
        self._card = QFrame()
        self._card.setObjectName("ConsoleCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        wrapper.addWidget(self._card)

        outer = QHBoxLayout(self._card)
        outer.setContentsMargins(0, 1, 6, 1)
        outer.setSpacing(4)

        # Conector estilo Polaris: "╰" à esquerda cria a hierarquia visual
        # pai→filho sem depender de indentação do QTreeWidget.
        self._connector_label = QLabel("")
        self._connector_label.setFixedWidth(18)
        self._connector_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._connector_label.setStyleSheet(
            "QLabel { color: #555555; font-size: 11px; background: transparent; border: 0; }"
        )
        outer.addWidget(self._connector_label)

        self._selection_strip = QFrame()
        self._selection_strip.setVisible(False)
        # Strip de estado mantido no DOM pra não quebrar _apply_card_qss/update_state
        # que chamam setStyleSheet nele — apenas oculto (largura 0).
        self._status_strip = QFrame()
        self._status_strip.setFixedWidth(0)
        self._status_strip.setVisible(False)
        self._status_strip.setObjectName("ConsoleStateStrip")
        self._selected = False
        self._apply_card_qss()

        outer.addWidget(self._status_strip)

        # Coluna do ícone (spinner ‖/⠋) foi removida do layout — a faixa
        # vertical de estado (`_status_strip`) mostra o estado em um glance,
        # sem duplicar sinal visual. O QLabel continua existindo (escondido)
        # pra manter compatibilidade com `update_state` que ainda chama
        # `setText` nele.
        self._icon = QLabel()
        self._icon.setVisible(False)


        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Title row: título + ações inline (✏ ▶ ⚙ ✖) à direita.
        # Visibilidade das ações controlada pelo toggle no header
        # WORKSPACES (set_actions_visible). Callbacks são injetadas
        # pelo MainWindow via set_action_callbacks.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(5)
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            f"color: {STATE_TITLE_COLOR[STATE_IDLE]}; font-size: 11px;"
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

        # Badge verde de runner(s) em execução neste console — pintado pelo
        # MainWindow a partir da RunnerArea console-scoped (running_count).
        self._runner_badge = QLabel("")
        self._runner_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._runner_badge.setStyleSheet(
            "QLabel {"
            "  background: rgba(90, 195, 138, 60);"
            "  color: #7ee0a0;"
            "  font-size: 9px; font-weight: 700;"
            "  padding: 1px 5px; border-radius: 6px;"
            "}"
        )
        self._runner_badge.hide()
        title_row.addWidget(self._runner_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Estado atual + elegibilidade pro ▶ continuar. O continue só faz
        # sentido em sessões restauradas no startup (--resume) que estão
        # ociosas — caso típico: app fechou no meio de uma tarefa e o
        # Claude voltou parado no prompt. Em todo outro estado o botão é
        # ruído visual (ou está rodando, ou aguardando decisão, ou é uma
        # sessão fresca que não tem nada pra continuar).
        self._current_state: str = STATE_IDLE
        self._continue_eligible: bool = False
        self._actions_user_visible: bool = True
        self._hovered: bool = False
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
        # uma linha do card na sidebar. `_full` guarda o texto inteiro
        # (sem truncar) pro tooltip do label de estado.
        self._last_action: str = ""
        self._last_action_full: str = ""
        # Snapshot duplicado dos dados que o footer global também
        # consome — guardados em campos próprios pra `status_info()`
        # poder devolver sem reparsear o QLabel.
        self._model: str = ""
        self._branch: str = ""
        self._modified: int = 0
        self._is_worktree: bool = False
        self._ahead: int = 0
        self._behind: int = 0
        self._git_files: list = []
        self._pr_urls: list[str] = []
        self._pr_chips: dict[str, QLabel] = {}
        # Nº de runners (console-scoped) em execução neste console agora.
        self._runner_running: int = 0

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
            "Continuar este console — manda 'continue' + Enter pro agente"
        )
        self._continue_btn.setEnabled(False)
        self._continue_btn.setVisible(False)
        actions_layout.addWidget(self._continue_btn)

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
        self._actions_widget.setVisible(False)
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
        # O ●N de modificados é um <a href="git"> — clique abre o painel
        # Git já focado neste console (signal open_git_requested).
        self._git_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._git_label.linkActivated.connect(
            lambda _href: self.open_git_requested.emit()
        )
        state_row.addWidget(self._git_label, 0, Qt.AlignmentFlag.AlignRight)

        self._pr_chips_container = QWidget()
        self._pr_chips_layout = QHBoxLayout(self._pr_chips_container)
        self._pr_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._pr_chips_layout.setSpacing(3)
        self._pr_chips_container.setVisible(False)
        state_row.addWidget(self._pr_chips_container, 0, Qt.AlignmentFlag.AlignRight)

        vbox.addLayout(state_row)

        outer.addLayout(vbox, stretch=1)

    def enterEvent(self, event) -> None:  # noqa: D401
        self._hovered = True
        self._refresh_actions_visibility()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401
        self._hovered = False
        self._refresh_actions_visibility()
        super().leaveEvent(event)

    def set_unread_count(self, count: int) -> None:
        """Pinta badge laranja com nº de notificações pendentes nessa sessão."""
        if count <= 0:
            self._notif_badge.hide()
            return
        self._notif_badge.setText(str(count) if count < 100 else "99+")
        self._notif_badge.show()

    def set_runner_running(self, count: int) -> None:
        """Pinta o badge verde ▶ com o nº de runners em execução neste
        console (console-scoped). Esconde quando não há nenhum rodando."""
        count = max(0, int(count))
        self._runner_running = count
        if count <= 0:
            self._runner_badge.hide()
            return
        self._runner_badge.setText("▶" if count == 1 else f"▶ {count}")
        self._runner_badge.setToolTip(
            "1 runner em execução neste console"
            if count == 1
            else f"{count} runners em execução neste console"
        )
        self._runner_badge.show()

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
            self._last_action_full = last_action
        elif state not in (STATE_AWAITING, STATE_IDLE):
            # Mantém a última ação ao parar pra pedir decisão / ficar
            # ocioso — o card preserva o contexto do que estava fazendo
            # ("Aguardando decisão · Editando foo.py"). Nos demais
            # estados, ação vazia limpa mesmo.
            self._last_action = ""
            self._last_action_full = ""
        self._state_label.setText(self._compose_state_text(state))
        self._refresh_state_tooltip(state)
        # Tinta o título com a cor do estado pra dar leitura rápida da
        # lista — sessões trabalhando ficam âmbar, aguardando laranja,
        # ociosas em cinza desbotado.
        self._title_label.setStyleSheet(
            f"color: {STATE_TITLE_COLOR[state]};"
            f" font-weight: 650; font-size: 11px;"
        )
        # Memoriza estado e reavalia visibilidade do ▶ — ele só aparece
        # em sessão restaurada+ociosa.
        self._current_state = state
        self._refresh_continue_visibility()
        # Atualiza a borda lateral colorida (state-driven).
        self._apply_card_qss()

    def _refresh_state_tooltip(self, state: str) -> None:
        """Tooltip do label de estado — estado + última ação completa
        (o label visível trunca em 55 chars)."""
        lines = [f"Estado: {STATE_LABEL[state]}"]
        full = _strip_noise(self._last_action_full) if self._last_action_full else ""
        if full:
            lines.append(f"Última ação: {full}")
        if state == STATE_IDLE and self._idle_since is not None:
            elapsed = int(time.monotonic() - self._idle_since)
            if elapsed >= 1:
                lines.append(f"Ocioso há {_fmt_elapsed(elapsed)}")
        self._state_label.setToolTip("\n".join(lines))

    def _compose_state_text(self, state: str) -> str:
        base = STATE_LABEL[state]
        if state == STATE_IDLE and self._idle_since is not None:
            elapsed = int(time.monotonic() - self._idle_since)
            if elapsed >= 1:
                base = f"{base} · {_fmt_elapsed(elapsed)}"
        clean = _strip_noise(self._last_action) if self._last_action else ""
        if clean:
            return f"{base} · {clean}"
        return base

    def tick_idle(self) -> None:
        """Re-renderiza o label de estado quando ocioso pra atualizar o
        cronômetro 'Ocioso · 2m 30s'. Chamado por um QTimer no MainWindow
        a cada segundo enquanto houver consoles ociosos."""
        if self._current_state != STATE_IDLE or self._idle_since is None:
            return
        self._state_label.setText(self._compose_state_text(STATE_IDLE))
        self._refresh_state_tooltip(STATE_IDLE)

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
        on_close: Callable[[], None] | None = None,
        on_rename: Callable[[], None] | None = None,
    ) -> None:
        """Conecta os cliques dos botões inline (▶ ✖)."""
        # Desconecta primeiro pra evitar duplicar handlers ao reconectar.
        # Só na 2ª+ chamada — disconnect() sem conexão prévia emite um
        # RuntimeWarning ruidoso (não um RuntimeError capturável).
        if getattr(self, "_actions_wired", False):
            for btn in (self._continue_btn, self._close_btn, self._rename_btn):
                try:
                    btn.clicked.disconnect()
                except RuntimeError:
                    pass
        self._actions_wired = True
        self._continue_btn.clicked.connect(lambda _=False: on_continue())
        if on_close is not None:
            self._close_btn.clicked.connect(lambda _=False: on_close())
        if on_rename is not None:
            self._rename_btn.clicked.connect(lambda _=False: on_rename())

    def _apply_card_qss(self) -> None:
        """Renderiza o console como item subordinado ao workspace."""
        state = getattr(self, "_current_state", STATE_IDLE)
        if self._selected:
            bg = "rgba(255, 255, 255, 8)"
        elif state == STATE_AWAITING:
            bg = "rgba(224, 144, 96, 9)"
        elif state == STATE_ERROR:
            bg = "rgba(213, 114, 114, 10)"
        else:
            bg = "transparent"
        strip_color = STATE_COLOR[state]
        self._card.setStyleSheet(
            f"#ConsoleCard {{"
            f"  background: {bg};"
            f"  border: 0;"
            f"  border-radius: 5px;"
            f"}}"
            f"#ConsoleCard:hover {{ background: rgba(255, 255, 255, 6); }}"
            f"#ConsoleStateStrip {{"
            f"  background: {strip_color};"
            f"  border-radius: 1px;"
            f"}}"
            f"#ConsoleCard QLabel {{ background: transparent; }}"
            f"#ConsoleCard QPushButton {{ background: transparent; }}"
            f"#ConsoleCard QWidget {{ background: transparent; }}"
        )

    def set_selected(self, selected: bool) -> None:
        """Pinta o background do card com tint discreto quando selecionado.
        Mantém a barra lateral colorida pelo estado — seleção vira só
        diferença de bg/borda externa."""
        self._selected = selected
        self._apply_card_qss()
        self._connector_label.setText("╰" if selected else "")
        # Seleção não mexe na cor do robô — ele segue sempre o estado
        # (sinalização de seleção fica no bg/borda do card e no conector).

    def set_actions_visible(self, visible: bool) -> None:
        """Mostra/esconde o bloco de ações inline (▶ ⚙) via toggle do
        header WORKSPACES. Quando oculto, o espaço é colapsado mas a
        altura total da row continua intacta."""
        self._actions_user_visible = visible
        self._refresh_actions_visibility()

    def _refresh_actions_visibility(self) -> None:
        visible = self._actions_user_visible and self._hovered
        self._actions_widget.setVisible(visible)
        self._close_btn.setVisible(visible)
        self._refresh_continue_visibility()

    def set_actions_enabled(self, enabled: bool) -> None:
        """Habilita/desabilita os botões conforme o terminal está rodando.
        O ✖ fica sempre habilitado — faz sentido remover mesmo console
        já encerrado (limpa a sidebar)."""
        self._continue_btn.setEnabled(enabled)
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
            and self._actions_user_visible
            and self._hovered
        )
        self._continue_btn.setVisible(should_show)

    def set_pr_url(self, url: str) -> None:
        """Compat: PR detectado sem estado conhecido (chip rosa). O
        poller de PR atualiza depois via set_pr_info com estado/cor."""
        self.set_pr_info(url)

    def set_pr_info(
        self, url: str, state: str = "", number: int = 0, draft: bool = False
    ) -> None:
        """Marca esta sessão com o PR/MR da branch — chip colorido pelo
        estado (aberto verde, draft cinza, merged roxo, fechado
        vermelho; rosa = estado desconhecido). Chips são indexados por
        URL: estado novo atualiza o chip existente in-place (OPEN→MERGED
        durante a sessão), sem duplicar. Clique abre o PR no browser."""
        url = (url or "").rstrip("/")
        if not url:
            return
        color, state_pt = _pr_state_style(state, draft)
        from ..services.runner_url_detect import pr_label_from_url
        label = pr_label_from_url(url)
        if state == "MERGED":
            label += " ✓"
        elif state == "CLOSED":
            label += " ✗"
        elif draft:
            label += " draft"
        chip = self._pr_chips.get(url)
        if chip is None:
            chip = QLabel()
            chip.setTextFormat(Qt.TextFormat.RichText)
            chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            chip.setMaximumHeight(16)
            chip.setTextInteractionFlags(
                Qt.TextInteractionFlag.LinksAccessibleByMouse
            )
            chip.linkActivated.connect(
                lambda href: QDesktopServices.openUrl(QUrl(href))
            )
            self._pr_chips[url] = chip
            self._pr_urls.append(url)
            self._pr_chips_layout.addWidget(chip)
        chip.setText(
            f"<a href='{url}' style='color: {color};"
            f" text-decoration: none;'>{label}</a>"
        )
        chip.setStyleSheet(theme.pr_chip_qss(color))
        tip = url if not state_pt else f"PR #{number} — {state_pt}\n{url}" if number else f"{state_pt}\n{url}"
        chip.setToolTip(tip)
        self._pr_chips_container.setVisible(True)

    def update_git_info(
        self,
        branch: str,
        modified: int,
        is_worktree: bool = False,
        ahead: int = 0,
        behind: int = 0,
        files: list | None = None,
        worktree_dir: str = "",
    ) -> None:
        """Atualiza o label do lado direito com branch, ↑ahead ↓behind e
        contagem de arquivos modificados (working tree + staged +
        untracked). `branch` vazio = pasta não é repo git → esconde o
        label. `is_worktree` ganha badge `wt` + glifo 🌿 verde — console
        rodando numa git worktree isolada. `files` (list[GitFile] do
        poller) alimenta o tooltip com a lista de arquivos — sem git
        extra. O ●N é clicável e emite `open_git_requested`.
        """
        self._branch = branch
        self._modified = modified
        self._is_worktree = is_worktree
        self._ahead = ahead
        self._behind = behind
        self._git_files = list(files) if files else []
        if not branch:
            self._git_label.setVisible(False)
            self._git_label.setText("")
            return
        # Encurta nomes longos pra não dominar a row do chip
        b = branch if len(branch) <= 18 else branch[:17] + "…"
        if is_worktree:
            glyph = (
                f"<span style='background: rgba(90, 195, 138, 0.18);"
                f" color: #5ac38a; font-weight: 700;'>&nbsp;wt&nbsp;</span>"
                f" <span style='color: #5ac38a;'>🌿 {b}</span>"
            )
        else:
            glyph = f"⎇ {b}"
        parts = [glyph]
        # ↑ahead ↓behind — omitidos quando 0 pra não poluir o chip.
        if ahead > 0:
            parts.append(f"<span style='color: {theme.SUCCESS};'>↑{ahead}</span>")
        if behind > 0:
            parts.append(f"<span style='color: {theme.WAITING};'>↓{behind}</span>")
        if modified > 0:
            parts.append(
                f"<a href='git' style='color: {theme.WARNING};"
                f" text-decoration: none;'>●{modified}</a>"
            )
        self._git_label.setText(" ".join(parts))
        self._git_label.setToolTip(
            self._compose_git_tooltip(branch, modified, worktree_dir)
        )
        self._git_label.setVisible(True)

    def _compose_git_tooltip(
        self, branch: str, modified: int, worktree_dir: str
    ) -> str:
        """Monta o tooltip do chip git só com dados já recebidos do
        poller — nenhum subprocess no hover."""
        head = f"Branch: {branch}"
        sync = []
        if self._ahead > 0:
            sync.append(f"↑{self._ahead} à frente")
        if self._behind > 0:
            sync.append(f"↓{self._behind} atrás")
        if sync:
            head += " · " + " ".join(sync)
        lines = [head]
        if self._is_worktree:
            lines.insert(0, "Worktree isolada 🌿")
            if worktree_dir:
                lines.insert(1, f"Path: {worktree_dir}")
        if modified > 0:
            lines.append(f"{modified} arquivo(s) modificado(s):")
            max_files = 10
            for gf in self._git_files[:max_files]:
                label = gf.label() if hasattr(gf, "label") else "?"
                path = getattr(gf, "path", str(gf))
                lines.append(f"  {label} — {path}")
            rest = len(self._git_files) - max_files
            if rest > 0:
                lines.append(f"  … e mais {rest} arquivo(s)")
            lines.append("Clique no ●N pra abrir o painel Git")
        else:
            lines.append("working tree limpo")
        return "\n".join(lines)

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
            "is_worktree": self._is_worktree,
            "ahead": self._ahead,
            "behind": self._behind,
            "runner_running": self._runner_running,
            "title": self._title,
            # `pr_url`: último MR/PR (compat). `pr_urls`: todos, pro footer
            # renderizar um link por MR quando a sessão tem várias pastas.
            "pr_url": self._pr_urls[-1] if self._pr_urls else None,
            "pr_urls": list(self._pr_urls),
        }


def _pr_state_style(state: str, draft: bool) -> tuple[str, str]:
    """(cor, label pt-BR) pro estado do PR/MR. Estado vazio = detectado
    sem consulta ainda → rosa clássico, sem label."""
    if draft and state == "OPEN":
        return theme.PR_DRAFT, "Draft"
    if state == "OPEN":
        return theme.PR_OPEN, "Aberto"
    if state == "MERGED":
        return theme.PR_MERGED, "Merged"
    if state == "CLOSED":
        return theme.PR_CLOSED, "Fechado"
    return theme.PR_PINK, ""


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
