"""Overlay de carregamento sobreposto a um widget (ex.: o pane do console).

Cobre o widget-pai com um véu semi-transparente + um **arco girando** desenhado
via paintEvent (~33fps, timer interno) — movimento contínuo e fluido, ao
contrário do glifo braille (100ms/frame) que lia como estático na janela curta
do overlay. Usado pra dar feedback visível na troca entre workspaces, quando a
1ª pintura da webview pode dar um respiro."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

_ARC_COLOR = "#6aa9e0"
_ARC_SIZE = 36          # px (lado do widget quadrado)
_ARC_SPAN_DEG = 100     # comprimento do arco
_ARC_STEP_DEG = 10      # graus por tick (10° a cada 30ms ≈ 1 volta/segundo)
_ARC_TICK_MS = 30       # ~33fps


class _ArcSpinner(QWidget):
    """Arco girando estilo 'material'. Anima sozinho enquanto visível
    (timer interno começa no showEvent e para no hideEvent)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_ARC_SIZE, _ARC_SIZE)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_ARC_TICK_MS)
        self._timer.timeout.connect(self._advance)

    def _advance(self) -> None:
        self._angle = (self._angle - _ARC_STEP_DEG) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
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
        p.drawArc(rect, self._angle * 16, _ARC_SPAN_DEG * 16)
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
