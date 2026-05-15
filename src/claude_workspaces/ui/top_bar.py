from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class TopBar(QWidget):
    """Barra superior global: toggle sidebar + logo + busca + botão Configurar.
    Substitui o QTabWidget anterior."""

    search_changed = Signal(str)
    search_submitted = Signal()
    settings_clicked = Signal()
    home_clicked = Signal()
    toggle_sidebar_clicked = Signal()

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

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por nome, pasta ou tarefa… (Ctrl+F)")
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

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def set_search_text(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)
