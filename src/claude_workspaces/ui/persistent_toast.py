"""Toast in-app frameless top-most — substitui (em parte) a notificação do
KDE Plasma quando ela some apesar de hints/urgency/resident/transient.

Posicionamento: top-right da tela primária. Quando há múltiplos toasts
(vários consoles em inbox), são empilhados pra baixo — mais novo embaixo.

Auto-dismiss com barra de progresso visível: o toast desaparece sozinho
depois de `duration_ms` (default 30s). Uma faixa fininha no rodapé encolhe
a cada tick mostrando quanto tempo falta. Hover pausa o timer (usuário
está lendo); sair do hover retoma.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
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
# Auto-dismiss default. ~30s dá tempo do usuário ver, ler e clicar
# sem precisar correr; menos que isso fica curto pra alertas de console.
DEFAULT_DURATION_MS = 30000
# Tick rate da barra de progresso. 50ms = animação suave (~20fps) sem
# pesar no event loop.
TICK_MS = 50
PROGRESS_BAR_HEIGHT = 3


class PersistentToast(QWidget):
    """Caixa frameless no canto da tela com título, body, botão "Abrir" e
    barra de progresso que mostra o tempo até auto-dismiss."""

    action_clicked = Signal()  # "Abrir console"
    snoozed = Signal()         # "Adiar 5min"
    seen = Signal()             # "Já vi"
    dismissed = Signal()       # X (some sem efeito no inbox)

    def __init__(
        self,
        title: str,
        body: str,
        duration_ms: int = DEFAULT_DURATION_MS,
        parent: QWidget | None = None,
    ) -> None:
        # Qt.Tool faz a janela não aparecer na taskbar; FramelessWindowHint
        # tira título/borda nativos; WindowStaysOnTopHint garante visibilidade
        # acima de outras apps mesmo sem foco.
        super().__init__(parent, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        # Não rouba foco ao aparecer — usuário continua digitando no que estava.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(WIDTH)

        self._duration_ms = max(1000, int(duration_ms))
        self._remaining_ms = self._duration_ms
        self._hover = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Card visual com bg/borda própria pra parecer um toast.
        card = QFrame(self)
        card.setObjectName("toastCard")
        card.setStyleSheet(
            "#toastCard {"
            "  background: #2b2b2b;"
            "  border: 1px solid #555;"
            "  border-top-left-radius: 6px;"
            "  border-top-right-radius: 6px;"
            "  border-bottom: 0;"
            "}"
            "#toastProgressContainer {"
            "  background: #1f1f1f;"
            "  border: 1px solid #555;"
            "  border-top: 0;"
            "  border-bottom-left-radius: 6px;"
            "  border-bottom-right-radius: 6px;"
            "}"
            "#toastProgressFill {"
            "  background: #3878c4;"
            "}"
            "QLabel#toastTitle { color: #fff; font-weight: 600; font-size: 13px; }"
            "QLabel#toastBody { color: #d8d8d8; font-size: 12px; }"
            "QPushButton#toastOpen {"
            "  background: #3878c4; color: #fff; border: 0;"
            "  border-radius: 3px; padding: 4px 10px; font-size: 12px;"
            "}"
            "QPushButton#toastOpen:hover { background: #4a8ad8; }"
            "QPushButton#toastSecondary {"
            "  background: #3a3a3a; color: #d8d8d8; border: 0;"
            "  border-radius: 3px; padding: 4px 8px; font-size: 11px;"
            "}"
            "QPushButton#toastSecondary:hover { background: #4a4a4a; color: #fff; }"
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

        # Action row: "Já vi" + "Adiar 5min" à esquerda, "Abrir console" à direita.
        # Botões secundários têm peso visual menor pra não competir com o CTA.
        action_row = QHBoxLayout()
        seen_btn = QPushButton("Já vi", card)
        seen_btn.setObjectName("toastSecondary")
        seen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        seen_btn.setToolTip("Marcar como visto e remover do inbox")
        seen_btn.clicked.connect(self._on_seen_clicked)
        action_row.addWidget(seen_btn)

        snooze_btn = QPushButton("Adiar 5min", card)
        snooze_btn.setObjectName("toastSecondary")
        snooze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        snooze_btn.setToolTip("Adiar lembrete por 5 minutos")
        snooze_btn.clicked.connect(self._on_snoozed_clicked)
        action_row.addWidget(snooze_btn)

        action_row.addStretch(1)
        open_btn = QPushButton("Abrir console", card)
        open_btn.setObjectName("toastOpen")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._on_action_clicked)
        action_row.addWidget(open_btn)
        card_lay.addLayout(action_row)

        # Container da barra de progresso (encosta no card, sem gap).
        # Usamos QFrame com largura manual em vez de QProgressBar porque
        # QProgressBar tem padding nativo do tema que polui o visual minimal.
        self._progress_container = QFrame(self)
        self._progress_container.setObjectName("toastProgressContainer")
        self._progress_container.setFixedHeight(PROGRESS_BAR_HEIGHT + 2)
        outer.addWidget(self._progress_container)

        self._progress_fill = QFrame(self._progress_container)
        self._progress_fill.setObjectName("toastProgressFill")
        self._progress_fill.setFixedHeight(PROGRESS_BAR_HEIGHT)
        self._progress_fill.move(1, 1)

        # Timer de auto-dismiss. setSingleShot=False pra disparar a cada
        # TICK_MS; quando _remaining_ms <= 0, dismiss.
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

    def update_content(self, title: str, body: str) -> None:
        """Atualiza texto e reseta o timer pra duração cheia (é um "novo aviso")."""
        self._title_label.setText(title)
        self._body_label.setText(body)
        self._remaining_ms = self._duration_ms
        self._update_progress_width()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._update_progress_width()
        self._tick_timer.start()

    def enterEvent(self, event: QEvent) -> None:  # type: ignore[override]
        # Hover pausa o auto-dismiss — usuário está lendo, não tira da frente.
        self._hover = True
        self._tick_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # type: ignore[override]
        self._hover = False
        self._tick_timer.start()
        super().leaveEvent(event)

    def _on_tick(self) -> None:
        self._remaining_ms -= TICK_MS
        if self._remaining_ms <= 0:
            self._tick_timer.stop()
            self._on_close_clicked()
            return
        self._update_progress_width()

    def _update_progress_width(self) -> None:
        # Container tem 1px de border cada lado; área útil = width - 2.
        container_w = self._progress_container.width()
        usable = max(0, container_w - 2)
        ratio = max(0.0, min(1.0, self._remaining_ms / self._duration_ms))
        self._progress_fill.setFixedWidth(int(usable * ratio))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_progress_width()

    def _on_action_clicked(self) -> None:
        self._tick_timer.stop()
        self.action_clicked.emit()
        self.hide()
        self.deleteLater()

    def _on_close_clicked(self) -> None:
        self._tick_timer.stop()
        self.dismissed.emit()
        self.hide()
        self.deleteLater()

    def _on_snoozed_clicked(self) -> None:
        self._tick_timer.stop()
        self.snoozed.emit()
        self.hide()
        self.deleteLater()

    def _on_seen_clicked(self) -> None:
        self._tick_timer.stop()
        self.seen.emit()
        self.hide()
        self.deleteLater()


def position_toasts(toasts: list[PersistentToast]) -> None:
    """Empilha os toasts no canto top-right da tela do cursor (multi-monitor).

    Mais antigo em cima, novos descem. Pra pegar altura real (body com
    word-wrap muda altura), forçamos `layout().activate()` + `adjustSize()`
    e depois lemos `frameGeometry().height()`. Se o widget ainda não foi
    realizado pelo Qt (height=0), cai pra sizeHint como aproximação.

    A função é idempotente: pode ser chamada após cada show/update/remove
    e sempre recalcula tudo do zero.
    """
    # Tela do cursor — multi-monitor: queremos os toasts onde o usuário
    # está olhando, não no monitor primário fixo.
    cursor_pos = QCursor.pos()
    screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    y = geo.top() + MARGIN
    x = geo.right() - MARGIN - WIDTH
    for toast in toasts:
        # Força layout a recalcular ANTES de medir; sem isso adjustSize
        # devolve sizeHint stale e dois toasts seguidos parecem ter a
        # mesma altura mesmo com body de tamanhos diferentes.
        lay = toast.layout()
        if lay is not None:
            lay.activate()
        toast.adjustSize()
        h = toast.frameGeometry().height() or toast.sizeHint().height()
        toast.move(QPoint(x, y))
        y += h + GAP


__all__ = ["PersistentToast", "position_toasts"]
