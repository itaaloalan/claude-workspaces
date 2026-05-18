"""Widget custom pros workspaces (top-level items da tree) — mostra o
nome do workspace + dois botões à direita:

    [nome do workspace]          [＋] [▾]

- `＋` abre um Claude novo no workspace (mesma ação de "Abrir Claude" /
  do botão "Abrir Claude" no detalhe / atalho).
- `▾`/`▸` colapsa/expande os filhos do workspace (consoles em execução
  + última sessão sugerida pra `--resume`).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from . import theme


_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: 4px;"
    f"  padding: 2px 6px;"
    f"  font-size: 13px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)


class WorkspaceItemWidget(QWidget):
    """Widget linha pra cada workspace top-level com botões inline."""

    def __init__(
        self,
        label: str,
        on_add_claude: Callable[[], None],
        on_toggle_collapse: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(28)

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(4)

        self._label = QLabel(label)
        bold = QFont(self._label.font())
        bold.setBold(True)
        self._label.setFont(bold)
        self._label.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self._label, stretch=1)

        self._add_btn = QPushButton("＋")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setFixedSize(22, 22)
        self._add_btn.setToolTip(
            "Abrir um Claude novo neste workspace (mesma ação do botão "
            "'Abrir Claude')"
        )
        self._add_btn.setStyleSheet(_BTN_QSS)
        self._add_btn.clicked.connect(on_add_claude)
        row.addWidget(self._add_btn)

        self._collapse_btn = QPushButton("▾")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setToolTip("Recolher / expandir os consoles deste workspace")
        self._collapse_btn.setStyleSheet(_BTN_QSS)
        self._collapse_btn.clicked.connect(on_toggle_collapse)
        row.addWidget(self._collapse_btn)

    def set_label(self, label: str) -> None:
        self._label.setText(label)

    def set_collapsed(self, collapsed: bool) -> None:
        """Atualiza o ícone do botão de colapsar pra refletir o estado
        atual do tree item (▸ recolhido, ▾ expandido)."""
        self._collapse_btn.setText("▸" if collapsed else "▾")
