from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QWidget,
)


class TopBar(QWidget):
    """Barra superior global: toggle sidebar + logo + tabs de console
    (GlobalConsoleTabBar via set_console_tabs) + inbox + Configurar.

    A busca saiu da barra — Ctrl+F foca a busca da sidebar."""

    settings_clicked = Signal()
    home_clicked = Signal()
    toggle_sidebar_clicked = Signal()
    toggle_right_dock_clicked = Signal()
    inbox_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setStyleSheet(
            "QWidget#TopBar { background: #131313; border-bottom: 1px solid #1f1f1f; }"
        )

        # Barra única e compacta (~38px) — a tab ativa já diz o workspace.
        self.setFixedHeight(38)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 12, 4)
        row.setSpacing(8)

        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        toggle_btn = QPushButton()
        toggle_btn.setIcon(_ic("fa5s.bars", color="#b8b8b8"))
        toggle_btn.setIconSize(_QS(16, 16))
        toggle_btn.setFlat(True)
        toggle_btn.setFixedSize(30, 30)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.setToolTip("Esconder / mostrar a barra lateral (Ctrl+B)")
        toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
            "QPushButton:hover { background: #1e1e1e; }"
        )
        toggle_btn.clicked.connect(self.toggle_sidebar_clicked.emit)
        row.addWidget(toggle_btn)

        # Logo Claude (robô) compacto — clicável pra voltar à home.
        logo = QPushButton()
        logo.setIcon(_ic("fa5s.robot", color="#cfcfcf"))
        logo.setIconSize(_QS(16, 16))
        logo.setFlat(True)
        logo.setFixedSize(30, 30)
        logo.setCursor(Qt.CursorShape.PointingHandCursor)
        logo.setToolTip("Claude Workspaces — voltar à home")
        logo.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 6px; }"
            "QPushButton:hover { background: #1e1e1e; }"
        )
        logo.clicked.connect(self.home_clicked.emit)
        row.addWidget(logo)

        # Slot central: GlobalConsoleTabBar (injetada via set_console_tabs).
        # Placeholder stretch até a MainWindow injetar.
        self._center_slot_index = row.count()
        row.addStretch(1)
        self._row = row

        # Bell de inbox — destaca quando há console aguardando atenção
        self._inbox_btn = QPushButton()
        self._inbox_btn.setIcon(_ic("fa5s.bell", color="#b8b8b8"))
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
        right_dock_btn.setIcon(_ic("fa5s.columns", color="#b8b8b8"))
        right_dock_btn.setIconSize(_QS(15, 15))
        right_dock_btn.setFlat(True)
        right_dock_btn.setFixedSize(30, 30)
        right_dock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        right_dock_btn.setToolTip("Esconder / mostrar painel de ferramentas (Ctrl+Shift+B)")
        right_dock_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 0; border-radius: 4px; }"
            "QPushButton:hover { background: #1e1e1e; }"
        )
        right_dock_btn.clicked.connect(self.toggle_right_dock_clicked.emit)
        row.addWidget(right_dock_btn)

        settings_btn = QPushButton("  Configurar")
        settings_btn.setIcon(_ic("fa5s.cog", color="#b8b8b8"))
        settings_btn.setIconSize(_QS(14, 14))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Configurações (Ctrl+,)")
        settings_btn.setStyleSheet(
            "QPushButton { background: #181818; color: #b8b8b8; "
            "border: 1px solid #262626; border-radius: 7px; padding: 6px 12px; }"
            "QPushButton:hover { border-color: #e6e6e6; color: #cfcfcf; }"
        )
        settings_btn.clicked.connect(self.settings_clicked.emit)
        row.addWidget(settings_btn)

    def add_right_widget(self, widget: QWidget) -> None:
        """Anexa um widget no fim da barra (ex.: WindowControls do modo
        frameless)."""
        self._row.addWidget(widget)

    def set_console_tabs(self, widget: QWidget) -> None:
        """Injeta a GlobalConsoleTabBar no slot central da barra
        (substitui o stretch placeholder)."""
        item = self._row.takeAt(self._center_slot_index)
        if item is not None and item.widget() is not None:
            item.widget().deleteLater()
        self._row.insertWidget(self._center_slot_index, widget, stretch=1)

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
                "  background: #9c6a3c; color: #fff; font-weight: 650;"
                "  border: 1px solid #9c6a3c; border-radius: 7px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { background: #dd9a63; border-color: #dd9a63; }"
            )
        else:
            self._inbox_btn.setIcon(_ic("fa5s.bell", color="#b8b8b8"))
            self._inbox_btn.setIconSize(_QS(15, 15))
            self._inbox_btn.setStyleSheet(
                "QPushButton {"
                "  background: #181818; color: #b8b8b8;"
                "  border: 1px solid #262626; border-radius: 7px;"
                "  padding: 6px 10px;"
                "}"
                "QPushButton:hover { border-color: #e6e6e6; color: #cfcfcf; }"
            )

