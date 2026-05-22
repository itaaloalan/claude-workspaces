"""Popup estilo VS Code pra trocar modo / effort / modelo da sessão Claude.

Inspirado no popup do plugin Claude do VS Code (Modes / Effort / Model).
Não temos API direta — só PTY, então:
- "Cicla modo": manda Shift+Tab (`\\x1b[Z`). Cada clique avança 1 posição.
- Os 5 itens de modo são INFORMATIVOS (descrevem o que cada modo faz);
  qualquer clique manda Shift+Tab, o usuário olha o indicador do Claude
  pra ver onde parou.
- "Trocar effort" / "Trocar modelo": abrem os slash commands `/effort`
  e `/model` no prompt do Claude.
"""

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

MODES = [
    ("✋", "Ask before edits", "Claude pede aprovação a cada edição"),
    ("⟨/⟩", "Edit automatically", "Edita direto sem pedir aprovação"),
    ("◧", "Plan mode", "Explora e apresenta plano antes de editar"),
    ("⚡", "Auto mode", "Escolhe sozinho o melhor modo por tarefa"),
    ("⚠", "Bypass permissions", "Não pede aprovação pra nada"),
]


def _row_button_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: transparent; color: {theme.TEXT_PRIMARY};"
        f"  border: 0; border-radius: 4px;"
        f"  padding: 6px 8px; text-align: left;"
        f"}}"
        f"QPushButton:hover {{ background: {theme.PRIMARY_HOVER_BG}; }}"
        f"QPushButton:pressed {{ background: {theme.PRIMARY}; color: {theme.TEXT_BRIGHT}; }}"
    )


class _ModeRow(QPushButton):
    """Botão linha (ícone + título + descrição em 2 linhas)."""

    def __init__(self, icon: str, title: str, desc: str, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_row_button_qss())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(22)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"color: {theme.TEXT_FADED}; font-size: 14px; font-family: monospace;"
        )
        layout.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;"
        )
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(f"color: {theme.TEXT_FADED}; font-size: 10px;")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(title_lbl)
        text_col.addWidget(desc_lbl)
        layout.addLayout(text_col, stretch=1)
        # Pra QPushButton aceitar layout filho ele precisa não ter texto
        # próprio — passamos "" pro super e desenhamos via labels.
        self.setText("")


class ModePopup(QWidget):
    """Popup flutuante com modos, effort e modelo.

    Callbacks:
    - on_cycle(): clique em qualquer modo (cicla via Shift+Tab no PTY)
    - on_effort(): manda /effort no prompt
    - on_model(): manda /model no prompt
    """

    def __init__(
        self,
        on_cycle: Callable[[], None],
        on_effort: Callable[[], None],
        on_model: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            f"ModePopup {{"
            f"  background: {theme.BG_PANEL};"
            f"  border: 1px solid {theme.BORDER};"
            f"  border-radius: 8px;"
            f"}}"
        )
        self.setMinimumWidth(320)

        self._on_cycle = on_cycle
        self._on_effort = on_effort
        self._on_model = on_model

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(2)

        # ----- Header -----
        header_row = QHBoxLayout()
        header_row.setContentsMargins(8, 4, 8, 4)
        title = QLabel("Modos")
        title.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: 0.5px;"
        )
        header_row.addWidget(title)
        header_row.addStretch()
        hint = QLabel("↹ Shift+Tab cicla")
        hint.setStyleSheet(f"color: {theme.TEXT_DISABLED}; font-size: 10px;")
        header_row.addWidget(hint)
        v.addLayout(header_row)

        # ----- Lista de modos (linhas clicáveis que ciclam) -----
        for icon, name, desc in MODES:
            row = _ModeRow(icon, name, desc)
            row.setToolTip(
                f"{name} — {desc}\n\nClique = Shift+Tab (cicla pra o próximo modo)."
                "\nClique várias vezes até o Claude mostrar o modo desejado."
            )
            row.clicked.connect(self._cycle_clicked)
            v.addWidget(row)

        v.addWidget(self._separator())

        # ----- Effort + Modelo -----
        effort_btn = _ModeRow(
            "⏻", "Trocar effort", "Abre /effort no prompt do Claude"
        )
        effort_btn.clicked.connect(self._effort_clicked)
        v.addWidget(effort_btn)

        model_btn = _ModeRow(
            "✦", "Trocar modelo", "Abre /model no prompt do Claude"
        )
        model_btn.clicked.connect(self._model_clicked)
        v.addWidget(model_btn)

        self.adjustSize()

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER}; border: 0;")
        return line

    def _cycle_clicked(self) -> None:
        try:
            self._on_cycle()
        finally:
            self.close()

    def _effort_clicked(self) -> None:
        try:
            self._on_effort()
        finally:
            self.close()

    def _model_clicked(self) -> None:
        try:
            self._on_model()
        finally:
            self.close()

    def show_at(self, global_pos) -> None:
        """Posiciona o popup de forma que não ultrapasse a tela."""
        from PySide6.QtGui import QGuiApplication

        self.adjustSize()
        screen = QGuiApplication.screenAt(global_pos)
        if screen is not None:
            geo = screen.availableGeometry()
            x = global_pos.x()
            y = global_pos.y()
            w = self.sizeHint().width()
            h = self.sizeHint().height()
            if x + w > geo.right():
                x = geo.right() - w - 4
            if y + h > geo.bottom():
                # abre pra cima quando não cabe pra baixo
                y = global_pos.y() - h
            self.move(x, max(geo.top() + 4, y))
        else:
            self.move(global_pos)
        self.show()

    def sizeHint(self) -> QSize:
        return QSize(self.minimumWidth(), super().sizeHint().height())
