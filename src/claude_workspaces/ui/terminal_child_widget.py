"""Widget custom pros children da sidebar tree — mostra o estado de um
console do Claude rodando num workspace, no estilo IntelliJ:

    [icon]  Console #N — claude       [▶] [⚙]   ← ações inline (toggle via header)
            Trabalhando · última ação do Claude
"""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
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
    STATE_IDLE: "#7a8a9a",
    STATE_DONE: theme.SUCCESS,
}

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
        # Altura aumentada pra caber a 3a linha de modelo + tokens. Quem
        # define a altura efetiva do row no QTreeWidget é o setSizeHint
        # no `_CHILD_HEIGHT` lá no main_window — manter sincronizado.
        self.setMinimumHeight(58)
        self.setMaximumHeight(58)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 2, 4, 2)
        outer.setSpacing(8)

        self._icon = QLabel("⠋")
        self._icon.setFixedSize(QSize(14, 38))
        self._icon.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self._icon.setStyleSheet(
            f"color: {theme.WARNING}; font-family: monospace; font-size: 12px;"
        )
        outer.addWidget(self._icon)

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

        title_row.addWidget(self._actions_widget)
        vbox.addLayout(title_row)

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

        self._sep_dot = QLabel("·")
        self._sep_dot.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: 10px;"
        )
        self._sep_dot.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        sub_row.addWidget(self._sep_dot)

        self._action_label = QLabel("")
        self._action_label.setStyleSheet(
            f"color: {theme.TEXT_FADED}; font-size: 10px;"
        )
        self._action_label.setWordWrap(False)
        self._action_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._action_label.setMaximumHeight(14)
        sub_row.addWidget(self._action_label, stretch=1)

        vbox.addLayout(sub_row)
        outer.addLayout(vbox, stretch=1)

        # Lado direito: branch + contagem de arquivos modificados do repo.
        # Atualizado em segundo plano pelo RepoStatusPoller (main_window).
        self._git_label = QLabel("")
        self._git_label.setTextFormat(Qt.TextFormat.RichText)
        self._git_label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px;"
        )
        self._git_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._git_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        self._git_label.setVisible(False)
        outer.addWidget(self._git_label)

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
        elif state == STATE_AWAITING:
            self._icon.setText("!")
        elif state == STATE_IDLE:
            self._icon.setText("❚❚")
        else:
            self._icon.setText("✓")
        self._icon.setStyleSheet(
            f"color: {STATE_COLOR[state]}; font-family: monospace; font-size: 12px;"
        )
        self._state_label.setText(STATE_LABEL[state])
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[state]};"
            f" font-size: 10px; font-weight: 600;"
            f" letter-spacing: 0.3px;"
        )
        if last_action:
            shown = last_action if len(last_action) <= 55 else last_action[:54] + "…"
            self._action_label.setText(shown)
            self._action_label.setVisible(True)
            self._sep_dot.setVisible(True)
        else:
            self._action_label.setVisible(False)
            self._sep_dot.setVisible(False)

    def set_action_callbacks(
        self,
        on_continue: Callable[[], None],
        on_open_mode_popup: Callable[[QWidget], None],
    ) -> None:
        """Conecta os cliques dos botões inline (▶ ⚙). `on_open_mode_popup`
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
        self._continue_btn.clicked.connect(lambda _=False: on_continue())
        self._mode_btn.clicked.connect(
            lambda _=False, b=self._mode_btn: on_open_mode_popup(b)
        )

    def set_actions_visible(self, visible: bool) -> None:
        """Mostra/esconde o bloco de ações inline (▶ ⚙). Quando oculto,
        o espaço é colapsado mas a altura total da row continua 42px."""
        self._actions_widget.setVisible(visible)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Habilita/desabilita os botões conforme o terminal está rodando."""
        self._continue_btn.setEnabled(enabled)
        self._mode_btn.setEnabled(enabled)

    def update_git_info(self, branch: str, modified: int) -> None:
        """Atualiza o label do lado direito com branch e contagem de
        arquivos modificados (working tree + staged + untracked).
        `branch` vazio = pasta não é repo git → esconde o label.
        """
        if not branch:
            self._git_label.setVisible(False)
            self._git_label.setText("")
            return
        # Encurta nomes longos pra não roubar espaço do action_label
        b = branch if len(branch) <= 18 else branch[:17] + "…"
        if modified > 0:
            self._git_label.setText(
                f"<span style='color: {theme.TEXT_FAINT};'>⎇ {b}</span>"
                f"  <span style='color: {theme.WARNING};'>●{modified}</span>"
            )
            tip = f"Branch: {branch} — {modified} arquivo(s) modificado(s)"
        else:
            self._git_label.setText(
                f"<span style='color: {theme.TEXT_FAINT};'>⎇ {b}</span>"
            )
            tip = f"Branch: {branch} — working tree limpo"
        self._git_label.setToolTip(tip)
        self._git_label.setVisible(True)
