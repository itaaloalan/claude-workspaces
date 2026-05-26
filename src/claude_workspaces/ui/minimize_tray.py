"""MinimizeTray — faixa que lista workspaces minimizados como chips.

Cada workspace minimizado vira um chip clicável aqui. Click no chip emite
`restore_requested(panel_id)` pra MainWindow restaurar o workspace.

A faixa fica oculta (setVisible False) quando não há chips. Quando há chips,
os chips quebram de linha via FlowLayout pra nunca forçar scroll horizontal.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .flow_layout import FlowLayout


class MinimizeTray(QWidget):
    restore_requested = Signal(str)  # panel_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MinimizeTray")
        self.setStyleSheet(
            "QWidget#MinimizeTray { background: #161616; "
            "border-top: 1px solid #2a2a2a; }"
        )
        # Não contribui pra largura mínima — evita scroll horizontal
        self.setMinimumWidth(0)
        self.hide()  # escondido por default

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        # Label "Minimizados:" — discreto
        self._lead = QLabel("Minimizados:")
        self._lead.setStyleSheet(
            "color: #707070; font-size: 10px; "
            "font-weight: 700; letter-spacing: 0.5px;"
        )
        outer.addWidget(self._lead)

        # Área de chips com FlowLayout — quebra de linha automática
        self._chips_widget = QWidget()
        self._chips_widget.setMinimumWidth(0)
        self._flow = FlowLayout(self._chips_widget, margin=0, h_spacing=6, v_spacing=4)
        outer.addWidget(self._chips_widget)

        self._chips: dict[str, QPushButton] = {}

    def add_chip(self, panel_id: str, label: str, icon_name: str | None = None) -> None:
        """Adiciona chip pro workspace minimizado. Idempotente."""
        if panel_id in self._chips:
            return
        btn = QPushButton(label)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setToolTip(f"Restaurar {label}")
        btn.setStyleSheet(
            "QPushButton { background: #1f1f1f; color: #c8c8c8; "
            "border: 1px solid #2c2c2c; border-radius: 10px; "
            "padding: 2px 12px; font-size: 11px; }"
            "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
        )
        if icon_name:
            from .icons import ic
            btn.setIcon(ic(icon_name, color="#9aa0a6"))
            btn.setIconSize(QSize(11, 11))
        btn.clicked.connect(lambda _=False, pid=panel_id: self._on_chip_clicked(pid))
        self._flow.addWidget(btn)
        self._chips[panel_id] = btn
        self._refresh_visibility()

    def remove_chip(self, panel_id: str) -> None:
        """Tira o chip do workspace (após restaurar)."""
        btn = self._chips.pop(panel_id, None)
        if btn is not None:
            btn.setParent(None)
            btn.deleteLater()
        self._refresh_visibility()

    def has_chip(self, panel_id: str) -> bool:
        return panel_id in self._chips

    def _on_chip_clicked(self, panel_id: str) -> None:
        self.restore_requested.emit(panel_id)

    def _refresh_visibility(self) -> None:
        self.setVisible(bool(self._chips))
