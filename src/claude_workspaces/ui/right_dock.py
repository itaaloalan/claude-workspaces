"""Dock direito estilo IntelliJ tool window:

- Strip vertical (~32px) sempre visível na borda direita, com um botão
  por painel registrado. Texto rotacionado -90° (sem dependência de
  ícones externos).
- Click no botão alterna abertura do painel à esquerda do strip;
  múltiplos podem estar abertos ao mesmo tempo (split vertical).
- Quando todos os painéis fechados, o dock fica só com a largura do
  strip — usuário ganha espaço pro restante da janela.
"""

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)


STRIP_WIDTH = 32


class VerticalTextButton(QPushButton):
    """Botão que pinta o texto rotacionado -90° (lê de baixo pra cima).
    Quando checked, fundo destaca; ao hover, levemente."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._label = label
        self.setText("")  # pintamos manualmente
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFixedWidth(STRIP_WIDTH)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(self._label)
        return QSize(STRIP_WIDTH, text_w + 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fundo conforme estado
        if self.isChecked():
            p.fillRect(self.rect(), QColor("#3d6ea8"))
            fg = QColor("#ffffff")
        elif self.underMouse():
            p.fillRect(self.rect(), QColor("#252a35"))
            fg = QColor("#e6e6e6")
        else:
            fg = QColor("#c8c8c8")

        # Texto rotacionado
        p.save()
        p.translate(self.width() - 6, self.height() - 8)
        p.rotate(-90)
        p.setPen(fg)
        f = p.font()
        f.setPointSize(max(f.pointSize(), 10))
        p.setFont(f)
        p.drawText(0, 0, self._label)
        p.restore()


class RightDock(QWidget):
    """Dock com tool-strip vertical + splitter de painéis."""

    panel_toggled = Signal(str, bool)  # panel_id, is_open

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panels: dict[str, tuple[VerticalTextButton, QWidget]] = {}
        self._panel_order: list[str] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Container do conteúdo (splitter vertical entre painéis abertos)
        self._content = QSplitter(Qt.Orientation.Vertical)
        self._content.setChildrenCollapsible(False)
        self._content.setHandleWidth(6)
        self._content.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )
        outer.addWidget(self._content, stretch=1)

        # Strip lateral fixo
        self._strip = QWidget()
        self._strip.setFixedWidth(STRIP_WIDTH)
        self._strip.setObjectName("DockStrip")
        self._strip.setStyleSheet(
            "QWidget#DockStrip {"
            "  background: #161616; border-left: 1px solid #2a2a2a;"
            "}"
        )
        sv = QVBoxLayout(self._strip)
        sv.setContentsMargins(0, 4, 0, 4)
        sv.setSpacing(2)
        sv.addStretch()
        self._strip_layout = sv
        outer.addWidget(self._strip)

        self._update_size_constraints()

    def add_panel(
        self, panel_id: str, label: str, content: QWidget, open_: bool = False
    ) -> None:
        btn = VerticalTextButton(label)
        btn.toggled.connect(
            lambda checked, pid=panel_id: self._on_btn_toggled(pid, checked)
        )
        # Insere antes do stretch final
        idx = self._strip_layout.count() - 1
        self._strip_layout.insertWidget(idx, btn)

        self._panels[panel_id] = (btn, content)
        self._panel_order.append(panel_id)

        # Pre-adiciona o widget ao splitter (escondido)
        self._content.addWidget(content)
        content.setVisible(False)

        if open_:
            btn.setChecked(True)  # dispara _on_btn_toggled
        else:
            self._update_size_constraints()

    def open_panels(self) -> list[str]:
        return [
            pid for pid, (btn, _) in self._panels.items() if btn.isChecked()
        ]

    def set_panel_open(self, panel_id: str, open_: bool) -> None:
        if panel_id in self._panels:
            self._panels[panel_id][0].setChecked(open_)

    def _on_btn_toggled(self, panel_id: str, checked: bool) -> None:
        if panel_id not in self._panels:
            return
        _, widget = self._panels[panel_id]
        widget.setVisible(checked)
        self._update_size_constraints()
        self.panel_toggled.emit(panel_id, checked)

    def _update_size_constraints(self) -> None:
        any_open = any(btn.isChecked() for btn, _ in self._panels.values())
        if any_open:
            # Permite o user redimensionar; usa um mínimo razoável
            self.setMinimumWidth(STRIP_WIDTH + 220)
            self.setMaximumWidth(16777215)
        else:
            self.setMinimumWidth(STRIP_WIDTH)
            self.setMaximumWidth(STRIP_WIDTH)
