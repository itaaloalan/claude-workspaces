"""Toast in-app frameless top-most — substitui a notificação do KDE Plasma
quando ela some apesar de hints/urgency/resident/transient.

Lifecycle 100% nosso: aparece via `show_toast`, some via `dismiss` (clique
no X ou no botão Abrir). Não usa o daemon de notificações, então não está
sujeito às regras de "qualquer notif com action vira transient" do Plasma.

Posicionamento: bottom-right da tela primária, com `MARGIN` de respiro.
Quando há múltiplos toasts (vários consoles em inbox), são empilhados pra
cima — cada novo toast soma a altura do anterior + GAP no offset Y.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

# Espaço da borda da tela e entre toasts empilhados.
MARGIN = 16
GAP = 8
WIDTH = 360


class PersistentToast(QWidget):
    """Caixa frameless no canto da tela com título, body e botão "Abrir"."""

    action_clicked = Signal()
    dismissed = Signal()

    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        # Qt.Tool faz a janela não aparecer na taskbar; FramelessWindowHint
        # tira título/borda nativos; WindowStaysOnTopHint garante visibilidade
        # acima de outras apps mesmo sem foco.
        super().__init__(parent, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        # Não rouba foco ao aparecer — usuário continua digitando no que estava.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Card visual com bg/borda própria pra parecer um toast — frameless
        # cru no Qt fica feio e sem affordance de "isso é uma notificação".
        card = QFrame(self)
        card.setObjectName("toastCard")
        card.setStyleSheet(
            "#toastCard {"
            "  background: #2b2b2b;"
            "  border: 1px solid #555;"
            "  border-radius: 6px;"
            "}"
            "QLabel#toastTitle { color: #fff; font-weight: 600; font-size: 13px; }"
            "QLabel#toastBody { color: #d8d8d8; font-size: 12px; }"
            "QPushButton#toastOpen {"
            "  background: #3878c4; color: #fff; border: 0;"
            "  border-radius: 3px; padding: 4px 10px; font-size: 12px;"
            "}"
            "QPushButton#toastOpen:hover { background: #4a8ad8; }"
            "QPushButton#toastClose {"
            "  background: transparent; color: #888; border: 0;"
            "  font-size: 14px; padding: 0 4px;"
            "}"
            "QPushButton#toastClose:hover { color: #fff; }"
        )
        outer.addWidget(card)

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 8, 10, 8)
        card_lay.setSpacing(4)

        # Header: título à esquerda, X à direita
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel(title, card)
        self._title_label.setObjectName("toastTitle")
        self._title_label.setWordWrap(True)
        header.addWidget(self._title_label, 1)

        close_btn = QPushButton("✕", card)
        close_btn.setObjectName("toastClose")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._on_close_clicked)
        header.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        card_lay.addLayout(header)

        # Body
        self._body_label = QLabel(body, card)
        self._body_label.setObjectName("toastBody")
        self._body_label.setWordWrap(True)
        card_lay.addWidget(self._body_label)

        # Action button
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        open_btn = QPushButton("Abrir console", card)
        open_btn.setObjectName("toastOpen")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._on_action_clicked)
        action_row.addWidget(open_btn)
        card_lay.addLayout(action_row)

    def update_content(self, title: str, body: str) -> None:
        self._title_label.setText(title)
        self._body_label.setText(body)

    def _on_action_clicked(self) -> None:
        self.action_clicked.emit()
        self.hide()
        self.deleteLater()

    def _on_close_clicked(self) -> None:
        self.dismissed.emit()
        self.hide()
        self.deleteLater()


def position_toasts(toasts: list[PersistentToast]) -> None:
    """Empilha os toasts no canto bottom-right da tela primária.

    Mais novo embaixo, antigos sobem. Recalcula tudo porque cada toast pode
    ter altura diferente (body com mais ou menos linhas).
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    y = geo.bottom() - MARGIN
    for toast in reversed(toasts):
        toast.adjustSize()
        h = toast.sizeHint().height()
        x = geo.right() - MARGIN - WIDTH
        toast.move(QPoint(x, y - h))
        y -= h + GAP


__all__ = ["PersistentToast", "position_toasts"]
