"""Widget custom pros children da sidebar tree — mostra o estado de um
console do Claude rodando num workspace, no estilo IntelliJ:

    [icon]  Console #N — claude
            Trabalhando            ← colorido por estado
            Lendo arquivo Foo.java ← última ação do Claude
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

# Estados visíveis na UI
STATE_WORKING = "working"
STATE_IDLE = "idle"
STATE_DONE = "done"


STATE_LABEL = {
    STATE_WORKING: "Trabalhando",
    STATE_IDLE: "Aguardando",
    STATE_DONE: "Concluído",
}

STATE_COLOR = {
    STATE_WORKING: "#e0b86a",  # amber
    STATE_IDLE: "#e09060",     # orange
    STATE_DONE: "#5ac35a",     # green
}


class TerminalChildWidget(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        # Tamanho previsível pra não brigar com o QTreeWidget no resize
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(48)
        self.setMaximumHeight(48)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 3, 6, 3)
        outer.setSpacing(6)

        self._icon = QLabel("⠋")
        self._icon.setFixedSize(QSize(16, 44))
        self._icon.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self._icon.setStyleSheet(
            "color: #e0b86a; font-family: monospace; font-size: 13px;"
        )
        outer.addWidget(self._icon)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            "color: #e6e6e6; font-weight: 600; font-size: 12px;"
        )
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(False)
        self._title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._title_label.setMaximumHeight(16)
        vbox.addWidget(self._title_label)

        self._state_label = QLabel(STATE_LABEL[STATE_IDLE])
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[STATE_IDLE]}; font-size: 10px;"
        )
        self._state_label.setWordWrap(False)
        self._state_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._state_label.setMaximumHeight(14)
        vbox.addWidget(self._state_label)

        self._action_label = QLabel("")
        self._action_label.setStyleSheet("color: #b0b0b0; font-size: 10px;")
        self._action_label.setWordWrap(False)
        self._action_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._action_label.setMaximumHeight(14)
        vbox.addWidget(self._action_label)

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
        # Reaplica elide com a largura real após o layout
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
        elif state == STATE_IDLE:
            self._icon.setText("❚❚")
        else:
            self._icon.setText("✓")
        self._icon.setStyleSheet(
            f"color: {STATE_COLOR[state]}; font-family: monospace; font-size: 13px;"
        )
        self._state_label.setText(STATE_LABEL[state])
        self._state_label.setStyleSheet(
            f"color: {STATE_COLOR[state]}; font-size: 11px;"
        )
        if last_action:
            # Trunca pra não estourar largura da sidebar
            shown = last_action if len(last_action) <= 55 else last_action[:54] + "…"
            self._action_label.setText(shown)
            self._action_label.setVisible(True)
        else:
            self._action_label.setVisible(False)
