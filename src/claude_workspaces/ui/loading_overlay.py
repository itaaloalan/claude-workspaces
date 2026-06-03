"""Overlay de carregamento sobreposto a um widget (ex.: o pane do console).

Cobre o widget-pai com um véu semi-transparente + um **arco girando** desenhado
via paintEvent. O ângulo é derivado do relógio (`time.monotonic()`), não de um
passo fixo por tick — assim QUALQUER repaint mostra o arco na posição real do
tempo decorrido, mesmo quando o event loop fica bloqueado pelo trabalho pesado
da troca de workspace e o timer de animação não consegue disparar. Usado pra
dar feedback visível na troca entre workspaces."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

_ARC_COLOR = "#6aa9e0"
_ARC_SIZE = 36          # px (lado do widget quadrado)
_ARC_SPAN_DEG = 100     # comprimento do arco
_ARC_DEG_PER_SEC = 500  # ≈ 1.4 voltas/segundo (mesma velocidade dos 8°/16ms)
_ARC_TICK_MS = 16       # ~60fps quando o event loop está livre


class _ArcSpinner(QWidget):
    """Arco girando estilo 'material'. O timer só agenda repaints; o ângulo
    vem do relógio — frames esparsos (event loop ocupado) ainda mostram
    rotação real em vez de arco congelado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_ARC_SIZE, _ARC_SIZE)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(_ARC_TICK_MS)
        self._timer.timeout.connect(self.update)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._t0 = time.monotonic()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        elapsed = time.monotonic() - self._t0
        angle = int(-(elapsed * _ARC_DEG_PER_SEC) % 360)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(_ARC_COLOR))
        pen.setWidthF(3.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        margin = 4.0
        rect = QRectF(
            margin, margin, self.width() - 2 * margin, self.height() - 2 * margin
        )
        # drawArc usa 1/16 de grau.
        p.drawArc(rect, angle * 16, _ARC_SPAN_DEG * 16)
        p.end()


class LoadingOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(14, 14, 14, 200);")
        # Não rouba clique/teclado: some rápido e não deve atrapalhar o foco.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner = _ArcSpinner(self)
        lay.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def cover(self, target: QWidget) -> None:
        """Posiciona o overlay cobrindo `target` (deve ser o parent), mostra
        no topo do z-order e força a pintura imediata (antes do trabalho
        pesado que vem em seguida)."""
        self.setGeometry(target.rect())
        self.raise_()
        self.show()
        self.repaint()

    def tick(self) -> None:
        """Força um frame síncrono do arco — pra usar entre passos de
        trabalho pesado, quando o event loop não respira pra processar o
        timer de animação. Com o ângulo vindo do relógio, cada tick mostra
        a posição real do tempo decorrido."""
        if self.isVisible():
            self._spinner.repaint()
