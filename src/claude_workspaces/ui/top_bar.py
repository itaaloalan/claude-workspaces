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
    toggle_right_dock_clicked = Signal()
    inbox_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setStyleSheet(
            "QWidget#TopBar { background: #181714; border-bottom: 1px solid #26241f; }"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 12, 6)
        row.setSpacing(8)

        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        toggle_btn = QPushButton()
        toggle_btn.setIcon(_ic("fa5s.bars", color="#c9c6c0"))
        toggle_btn.setIconSize(_QS(16, 16))
        toggle_btn.setFlat(True)
        toggle_btn.setFixedSize(30, 30)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.setToolTip("Esconder / mostrar a barra lateral (Ctrl+B)")
        toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
            "QPushButton:hover { background: #22201c; }"
        )
        toggle_btn.clicked.connect(self.toggle_sidebar_clicked.emit)
        row.addWidget(toggle_btn)

        # Logo Claude (robô) + título — clicáveis pra voltar à home.
        logo = QPushButton("  Claude Workspaces")
        logo.setIcon(_ic("fa5s.robot", color="#e0b268"))
        logo.setIconSize(_QS(16, 16))
        logo.setFlat(True)
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.setStyleSheet(
            "QPushButton { font-weight: 700; color: #e8e6e3; font-size: 13px; "
            "padding: 4px 6px; background: transparent; border: 0; border-radius: 6px; "
            "text-align: left; }"
            "QPushButton:hover { color: #e0b268; background: #22201c; }"
        )
        logo.clicked.connect(self.home_clicked.emit)
        row.addWidget(logo)

        # Workspace ativo: chip proeminente ao lado do logo. Atualizado
        # via set_active_workspace(name). Escondido quando não há ws.
        self._ws_chip = QPushButton()
        self._ws_chip.setIcon(_ic("fa5s.folder-open", color="#5ac35a"))
        self._ws_chip.setIconSize(_QS(13, 13))
        self._ws_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ws_chip.setToolTip("Workspace selecionado — click pra ir pra home")
        self._ws_chip.setStyleSheet(
            "QPushButton { background: rgba(90, 195, 90, 20); "
            "color: #dfeee0; font-weight: 650; font-size: 12px; "
            "border: 1px solid rgba(90, 195, 90, 42); border-radius: 12px; "
            "padding: 4px 12px; }"
            "QPushButton:hover { background: rgba(90, 195, 90, 34); "
            "border-color: rgba(90, 195, 90, 90); }"
        )
        self._ws_chip.clicked.connect(self.home_clicked.emit)
        self._ws_chip.setVisible(False)
        row.addWidget(self._ws_chip)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por nome, pasta ou sessão… (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(380)
        self.search.setStyleSheet(
            "QLineEdit { background: #1c1b18; border: 1px solid #26241f; "
            "border-radius: 6px; padding: 6px 10px; color: #e8e6e3; }"
            "QLineEdit:hover { border-color: #26241f; }"
            "QLineEdit:focus { border-color: #d4a04a; background: #181714; }"
        )
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.returnPressed.connect(self.search_submitted.emit)
        row.addWidget(self.search, stretch=1)

        row.addStretch()

        # Bell de inbox — destaca quando há console aguardando atenção
        self._inbox_btn = QPushButton()
        self._inbox_btn.setIcon(_ic("fa5s.bell", color="#c9c6c0"))
        self._inbox_btn.setIconSize(_QS(15, 15))
        self._inbox_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inbox_btn.setToolTip("Consoles aguardando atenção")
        self._inbox_count = 0
        self._refresh_inbox_btn_style()
        self._inbox_btn.clicked.connect(self.inbox_clicked.emit)
        row.addWidget(self._inbox_btn)

        # Toggle do dock direito (Ferramentas: Git/Skills/Arquivos/Memória).
        # Simétrico ao toggle da sidebar esquerda — antes só dava pra
        # exibir/esconder via Ctrl+Shift+B, sem botão visível.
        right_dock_btn = QPushButton()
        right_dock_btn.setIcon(_ic("fa5s.columns", color="#c9c6c0"))
        right_dock_btn.setIconSize(_QS(15, 15))
        right_dock_btn.setFlat(True)
        right_dock_btn.setFixedSize(30, 30)
        right_dock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        right_dock_btn.setToolTip("Esconder / mostrar painel de ferramentas (Ctrl+Shift+B)")
        right_dock_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
            "QPushButton:hover { background: #22201c; }"
        )
        right_dock_btn.clicked.connect(self.toggle_right_dock_clicked.emit)
        row.addWidget(right_dock_btn)

        settings_btn = QPushButton("  Configurar")
        settings_btn.setIcon(_ic("fa5s.cog", color="#c9c6c0"))
        settings_btn.setIconSize(_QS(14, 14))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Configurações (Ctrl+,)")
        settings_btn.setStyleSheet(
            "QPushButton { background: #1c1b18; color: #c9c6c0; "
            "border: 1px solid #2d2b26; border-radius: 7px; padding: 6px 12px; }"
            "QPushButton:hover { border-color: #d4a04a; color: #e0b268; }"
        )
        settings_btn.clicked.connect(self.settings_clicked.emit)
        row.addWidget(settings_btn)

        # Atalho Ctrl+F foca a busca da topbar
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+L"), self, self._focus_search)

    def set_active_workspace(self, name: str | None) -> None:
        """Atualiza o chip de workspace ativo. None oculta."""
        if not name:
            self._ws_chip.setVisible(False)
            return
        self._ws_chip.setText(f"  {name}")
        self._ws_chip.setVisible(True)

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
                "  background: #b86d2a; color: #fff; font-weight: 650;"
                "  border: 1px solid #b86d2a; border-radius: 7px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { background: #ec8f3a; border-color: #ec8f3a; }"
            )
        else:
            self._inbox_btn.setIcon(_ic("fa5s.bell", color="#c9c6c0"))
            self._inbox_btn.setIconSize(_QS(15, 15))
            self._inbox_btn.setStyleSheet(
                "QPushButton {"
                "  background: #1c1b18; color: #c9c6c0;"
                "  border: 1px solid #2d2b26; border-radius: 7px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { border-color: #d4a04a; color: #e0b268; }"
            )

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def set_search_text(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)
