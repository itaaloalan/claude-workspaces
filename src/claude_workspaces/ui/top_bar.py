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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setStyleSheet(
            "QWidget#TopBar { background: #161616; border-bottom: 1px solid #2a2a2a; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 12, 8)
        row.setSpacing(10)

        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        toggle_btn = QPushButton()
        toggle_btn.setIcon(_ic("fa5s.bars", color="#c8c8c8"))
        toggle_btn.setIconSize(_QS(16, 16))
        toggle_btn.setFlat(True)
        toggle_btn.setFixedSize(32, 32)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.setToolTip("Esconder / mostrar a barra lateral (Ctrl+B)")
        toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
            "QPushButton:hover { background: #2a2a2a; }"
        )
        toggle_btn.clicked.connect(self.toggle_sidebar_clicked.emit)
        row.addWidget(toggle_btn)

        # Logo Claude (robô) + título — clicáveis pra voltar à home.
        logo = QPushButton("  Claude Workspaces")
        logo.setIcon(_ic("fa5s.robot", color="#6aa9e0"))
        logo.setIconSize(_QS(16, 16))
        logo.setFlat(True)
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.setStyleSheet(
            "QPushButton { font-weight: 700; color: #e6e6e6; font-size: 13px; "
            "padding: 4px 6px; background: transparent; border: 0; border-radius: 4px; "
            "text-align: left; }"
            "QPushButton:hover { color: #6aa9e0; background: #2a2a2a; }"
        )
        logo.clicked.connect(self.home_clicked.emit)
        row.addWidget(logo)

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
        self._inbox_btn = QPushButton()
        self._inbox_btn.setIcon(_ic("fa5s.bell", color="#c8c8c8"))
        self._inbox_btn.setIconSize(_QS(15, 15))
        self._inbox_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inbox_btn.setToolTip("Consoles aguardando atenção")
        self._inbox_count = 0
        self._refresh_inbox_btn_style()
        self._inbox_btn.clicked.connect(self.inbox_clicked.emit)
        row.addWidget(self._inbox_btn)

        settings_btn = QPushButton("  Configurar")
        settings_btn.setIcon(_ic("fa5s.cog", color="#c8c8c8"))
        settings_btn.setIconSize(_QS(14, 14))
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
        # Texto só com o número quando há alerta — ícone vem do qtawesome
        self._inbox_btn.setText(f"  {count}" if count > 0 else "")
        self._refresh_inbox_btn_style()

    def _refresh_inbox_btn_style(self) -> None:
        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic
        if self._inbox_count > 0:
            self._inbox_btn.setIcon(_ic("fa5s.bell", color="#fff"))
            self._inbox_btn.setIconSize(_QS(15, 15))
            self._inbox_btn.setStyleSheet(
                "QPushButton {"
                "  background: #c9772d; color: #fff; font-weight: 600;"
                "  border: 1px solid #c9772d; border-radius: 6px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { background: #e0892f; border-color: #e0892f; }"
            )
        else:
            self._inbox_btn.setIcon(_ic("fa5s.bell", color="#c8c8c8"))
            self._inbox_btn.setIconSize(_QS(15, 15))
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
