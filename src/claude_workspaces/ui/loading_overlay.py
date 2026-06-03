"""Overlay de carregamento sobreposto a um widget (ex.: o pane do console).

Cobre o widget-pai com um véu semi-transparente + um glifo de spinner grande
centralizado. É só "view": quem anima é um `Spinner` externo (main_window),
que chama `set_frame()` a cada tick. Usado pra dar feedback visível na troca
entre workspaces, quando a 1ª pintura da webview pode dar um respiro."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


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
        self._glyph = QLabel("⠋")
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setStyleSheet(
            "color: #6aa9e0; font-size: 34px; background: transparent;"
        )
        lay.addWidget(self._glyph)
        self.hide()

    def set_frame(self, frame: str) -> None:
        self._glyph.setText(frame)

    def cover(self, target: QWidget) -> None:
        """Posiciona o overlay cobrindo `target` (deve ser o parent), mostra
        no topo do z-order e força a pintura imediata (antes do trabalho
        pesado que vem em seguida)."""
        self.setGeometry(target.rect())
        self.raise_()
        self.show()
        self.repaint()
