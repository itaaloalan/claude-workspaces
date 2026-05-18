"""Widget custom pros workspaces (top-level items da tree) — mostra o
nome + indicador de "rodando" (bolinha verde + badge de count) + botões:

    [nome do workspace] [●] [×N]          [＋] [▾]

- A bolinha verde aparece quando há ≥1 terminal Claude rodando no
  workspace; o badge `×N` aparece a partir de 2.
- `＋` abre um Claude novo no workspace (mesma ação de "Abrir Claude" /
  do botão "Abrir Claude" no detalhe / atalho).
- `▾`/`▸` colapsa/expande os filhos do workspace (consoles em execução).
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

# Bolinha verde: QLabel vazia com border-radius (mais limpa que o
# caractere "●", que herda cor/tamanho da fonte e renderiza desalinhado).
_DOT_QSS = (
    f"QLabel {{"
    f"  background-color: {theme.SUCCESS};"
    f"  border-radius: 4px;"
    f"}}"
)

# Pill com count quando há >1 terminal rodando — fundo verde transparente
# pra combinar com a bolinha sem competir com o nome do workspace.
_BADGE_QSS = (
    f"QLabel {{"
    f"  background: rgba(90, 195, 90, 38);"
    f"  color: {theme.SUCCESS};"
    f"  font-size: 9px;"
    f"  font-weight: 700;"
    f"  padding: 1px 5px;"
    f"  border-radius: 7px;"
    f"}}"
)


class WorkspaceItemWidget(QWidget):
    """Widget linha pra cada workspace top-level com botões inline."""

    def __init__(
        self,
        name: str,
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

        self._label = QLabel(name)
        label_font = QFont(self._label.font())
        label_font.setBold(True)
        label_font.setPointSizeF(label_font.pointSizeF() + 1.5)
        self._label.setFont(label_font)
        self._label.setStyleSheet("color: #f2f2f2;")
        self._label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        row.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._dot = QLabel("")
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(_DOT_QSS)
        self._dot.setToolTip("Há Claude rodando neste workspace")
        self._dot.hide()
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._badge = QLabel("")
        self._badge.setStyleSheet(_BADGE_QSS)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()
        row.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)

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

    def set_running_count(self, count: int) -> None:
        """Atualiza o indicador de "rodando" — bolinha verde (count≥1)
        + badge ×N (count>1). Esconde tudo quando count == 0."""
        if count <= 0:
            self._dot.hide()
            self._badge.hide()
            return
        self._dot.show()
        if count > 1:
            self._badge.setText(f"×{count}")
            self._badge.show()
        else:
            self._badge.hide()

    def set_collapsed(self, collapsed: bool) -> None:
        """Atualiza o ícone do botão de colapsar pra refletir o estado
        atual do tree item (▸ recolhido, ▾ expandido)."""
        self._collapse_btn.setText("▸" if collapsed else "▾")
