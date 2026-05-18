from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class TopBar(QWidget):
    """Barra superior global: toggle sidebar + logo + busca + inbox + Configurar."""

    search_changed = Signal(str)
    search_submitted = Signal()
    settings_clicked = Signal()
    home_clicked = Signal()
    toggle_sidebar_clicked = Signal()
    inbox_clicked = Signal()
    toggle_terminal_actions_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setStyleSheet(
            "QWidget#TopBar { background: #161616; border-bottom: 1px solid #2a2a2a; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 12, 8)
        row.setSpacing(10)

        toggle_btn = QPushButton("☰")
        toggle_btn.setFlat(True)
        toggle_btn.setFixedWidth(32)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.setToolTip("Esconder / mostrar a barra lateral (Ctrl+B)")
        toggle_btn.setStyleSheet(
            "QPushButton { color: #c8c8c8; font-size: 16px; padding: 4px; }"
            "QPushButton:hover { color: #6aa9e0; }"
        )
        toggle_btn.clicked.connect(self.toggle_sidebar_clicked.emit)
        row.addWidget(toggle_btn)

        logo = QPushButton("Claude Workspaces")
        logo.setFlat(True)
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.setStyleSheet(
            "QPushButton { font-weight: 700; color: #e6e6e6; font-size: 13px; padding: 4px 0; }"
            "QPushButton:hover { color: #6aa9e0; }"
        )
        logo.clicked.connect(self.home_clicked.emit)
        row.addWidget(logo)

        # Toggle global da toolbar de ações dos terminais (Continuar /
        # Ciclar / Effort / Modelo / Encerrar). Posicionado logo após
        # "Claude Workspaces" pra ficar discoverable. Texto/ícone do
        # botão é refrescado por set_terminal_actions_visible.
        self._terminal_actions_btn = QPushButton()
        self._terminal_actions_btn.setFlat(True)
        self._terminal_actions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terminal_actions_btn.setStyleSheet(
            "QPushButton { color: #c8c8c8; font-size: 12px; padding: 4px 8px;"
            " border: 1px solid #2c2c2c; border-radius: 6px; background: #1f1f1f; }"
            "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
        )
        self._terminal_actions_btn.clicked.connect(
            self.toggle_terminal_actions_clicked.emit
        )
        # Estado inicial = visível (settings default). MainWindow chama
        # `set_terminal_actions_visible` no boot pra refletir o que tá salvo.
        self.set_terminal_actions_visible(True)
        row.addWidget(self._terminal_actions_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por nome, pasta ou sessão… (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(380)
        self.search.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 6px; padding: 6px 10px; color: #e6e6e6; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.returnPressed.connect(self.search_submitted.emit)
        row.addWidget(self.search, stretch=1)

        row.addStretch()

        # Bell de inbox — destaca quando há console aguardando atenção
        self._inbox_btn = QPushButton("🔔")
        self._inbox_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inbox_btn.setToolTip("Consoles aguardando atenção")
        self._inbox_count = 0
        self._refresh_inbox_btn_style()
        self._inbox_btn.clicked.connect(self.inbox_clicked.emit)
        row.addWidget(self._inbox_btn)

        settings_btn = QPushButton("⚙ Configurar")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Configurações (Ctrl+,)")
        settings_btn.setStyleSheet(
            "QPushButton { background: #1f1f1f; color: #e6e6e6; "
            "border: 1px solid #2c2c2c; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
        )
        settings_btn.clicked.connect(self.settings_clicked.emit)
        row.addWidget(settings_btn)

        # Atalho Ctrl+F foca a busca da topbar
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+L"), self, self._focus_search)

    def set_inbox_count(self, count: int) -> None:
        self._inbox_count = count
        if count > 0:
            self._inbox_btn.setText(f"🔔 {count}")
        else:
            self._inbox_btn.setText("🔔")
        self._refresh_inbox_btn_style()

    def _refresh_inbox_btn_style(self) -> None:
        if self._inbox_count > 0:
            self._inbox_btn.setStyleSheet(
                "QPushButton {"
                "  background: #c9772d; color: #fff; font-weight: 600;"
                "  border: 1px solid #c9772d; border-radius: 6px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { background: #e0892f; border-color: #e0892f; }"
            )
        else:
            self._inbox_btn.setStyleSheet(
                "QPushButton {"
                "  background: #1f1f1f; color: #c8c8c8;"
                "  border: 1px solid #2c2c2c; border-radius: 6px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
            )

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def set_search_text(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)

    def set_terminal_actions_visible(self, visible: bool) -> None:
        """Atualiza rótulo/tooltip do botão de toggle pra refletir o estado
        atual da toolbar de ações dos terminais."""
        if visible:
            self._terminal_actions_btn.setText("⌃ Ações")
            self._terminal_actions_btn.setToolTip(
                "Ocultar a barra de ações (Continuar / Ciclar modo / Effort /"
                " Modelo / Encerrar) em todos os terminais. As mesmas ações"
                " continuam disponíveis no menu de contexto da sidebar."
            )
        else:
            self._terminal_actions_btn.setText("⌄ Ações")
            self._terminal_actions_btn.setToolTip(
                "Mostrar a barra de ações (Continuar / Ciclar modo / Effort /"
                " Modelo / Encerrar) em todos os terminais."
            )
