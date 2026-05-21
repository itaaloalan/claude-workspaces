"""Header widget pro grupo "Runners" na sidebar.

Aparece como item filho do workspace (ou do console) quando há ao menos
um runner naquele escopo. Os RunnerChildWidget ficam aninhados sob ele,
então o usuário pode recolher tudo de uma vez pela seta da tree.

    [Runners workspace]                              [＋]

O botão ＋ abre o diálogo de criação de runner no escopo correto.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
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
    f"  padding: 0px 4px;"
    f"  font-size: 12px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)


class RunnerGroupWidget(QWidget):
    """Linha de header pro grupo colapsável de runners."""

    def __init__(
        self,
        label: str,
        on_add_blank: Callable[[], None],
        on_generate: Callable[[], None] | None = None,
        on_toggle_collapse: Callable[[], None] | None = None,
        on_stop_all: Callable[[], None] | None = None,
        on_restart_all: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(22)
        self.setMaximumHeight(24)

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 4, 2)
        row.setSpacing(6)

        self._collapse_btn = QPushButton("⌄")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setFixedSize(18, 18)
        self._collapse_btn.setStyleSheet(_BTN_QSS)
        self._collapse_btn.setToolTip("Recolher / expandir runners")
        if on_toggle_collapse is not None:
            self._collapse_btn.clicked.connect(on_toggle_collapse)
        row.addWidget(self._collapse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Ícone SVG (mdi6.source-branch) à esquerda do label — simetria
        # com o bucket Sessões Claude que já tem ícone fa5s.comments.
        from PySide6.QtCore import QSize as _QS
        from .icons import ic as _ic
        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(
            _ic("mdi6.source-branch", color="#9aa0a6").pixmap(_QS(12, 12))
        )
        row.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(label)
        font = QFont(self._label.font())
        font.setPointSizeF(font.pointSizeF() - 0.5)
        self._label.setFont(font)
        self._label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-weight: 600;"
        )
        row.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Badge de contagem (escondido se 0/None) — mesmo visual do
        # bucket Sessões Claude na sidebar.
        self._count_badge = QLabel("")
        self._count_badge.setStyleSheet(
            "QLabel { background: #2a2a2a; color: #9aa0a6; font-size: 9px; "
            "font-weight: 700; padding: 1px 6px; border-radius: 6px; }"
        )
        self._count_badge.setVisible(False)
        row.addWidget(self._count_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)

        if on_restart_all is not None:
            self._restart_all_btn = QPushButton("↻")
            self._restart_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._restart_all_btn.setFixedSize(20, 18)
            self._restart_all_btn.setToolTip("Reiniciar todos os runners deste escopo")
            self._restart_all_btn.setStyleSheet(_BTN_QSS)
            self._restart_all_btn.clicked.connect(on_restart_all)
            row.addWidget(self._restart_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        if on_stop_all is not None:
            self._stop_all_btn = QPushButton("■")
            self._stop_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._stop_all_btn.setFixedSize(20, 18)
            self._stop_all_btn.setToolTip("Parar todos os runners deste escopo")
            self._stop_all_btn.setStyleSheet(_BTN_QSS)
            self._stop_all_btn.clicked.connect(on_stop_all)
            row.addWidget(self._stop_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._add_btn = QPushButton("＋")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setFixedSize(20, 18)
        self._add_btn.setToolTip("Novo runner neste escopo")
        self._add_btn.setStyleSheet(_BTN_QSS)
        self._on_add_blank = on_add_blank
        self._on_generate = on_generate
        self._add_btn.clicked.connect(self._open_add_menu)
        row.addWidget(self._add_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_count(self, count: int | None) -> None:
        """Mostra '[N]' à direita do label. None ou 0 esconde."""
        if not count:
            self._count_badge.setVisible(False)
            return
        self._count_badge.setText(str(count))
        self._count_badge.setVisible(True)

    def set_collapsed(self, collapsed: bool) -> None:
        """Atualiza o ícone do chevron (› recolhido, ⌄ expandido)."""
        self._collapse_btn.setText("›" if collapsed else "⌄")

    def _open_add_menu(self) -> None:
        # Se não tem gerador (escopo console-pending sem area), abre direto.
        if self._on_generate is None:
            self._on_add_blank()
            return
        menu = QMenu(self)
        a_blank = menu.addAction("Em branco")
        a_blank.triggered.connect(lambda: self._on_add_blank())
        a_gen = menu.addAction("Gerar com Claude")
        a_gen.triggered.connect(lambda: self._on_generate())
        menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))
