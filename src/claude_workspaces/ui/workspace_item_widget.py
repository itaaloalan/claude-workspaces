"""Widget custom pros workspaces (top-level items da tree) — mostra o
nome + indicador de "rodando" (bolinha verde + badge de count) + botões:

    [nome do workspace] [●] [×N]          [＋] [▾]

- A bolinha verde aparece quando há ≥1 terminal Claude rodando no
  workspace; o badge `×N` aparece a partir de 2.
- `＋` abre um Claude novo no workspace (mesma ação de "Abrir Claude" /
  do botão "Abrir Claude" no detalhe / atalho).
- `⌄`/`›` colapsa/expande os filhos do workspace (consoles em execução).
  Chevrons foram escolhidos no lugar de `▾`/`▸` porque o triângulo
  apontado pra direita parecia botão de play.
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
        # Altura aumentada pra dar respiro entre workspaces — antes ficavam
        # "colados" um no outro porque o header tinha exatamente a altura
        # do label + 4px de padding. Agora 8px extras separam visualmente.
        self.setMinimumHeight(28)

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 4)
        row.setSpacing(6)

        # Ícone do workspace antes do nome — match com mockup que mostra
        # um pequeno avatar/logo. fa5s.folder é o default; podia ser
        # detectado pelo stack (fa5b.git-alt se é repo git, etc) mas
        # pra evitar complexidade fica no folder por enquanto.
        from PySide6.QtCore import QSize as _QS

        self._ws_icon = QLabel()
        self._ws_icon_size = _QS(14, 14)
        # Cor da pasta reage à seleção (set_selected): azul quando
        # selecionado, branco "off" quando não.
        self._ws_icon_color_selected = "#6aa9e0"
        self._ws_icon_color_unselected = "#e6e6e6"
        self._ws_icon.setFixedSize(16, 16)
        row.addWidget(self._ws_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(name)
        label_font = QFont(self._label.font())
        label_font.setBold(True)
        label_font.setPointSizeF(label_font.pointSizeF() + 1.5)
        self._label.setFont(label_font)
        self._label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        # Cor reage à seleção (set_selected); default = não selecionado.
        self._selected = False
        self._apply_label_color()
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

        # Badge de notificações pendentes (laranja) — independente do badge
        # verde de "rodando". Pintado pelo MainWindow via NotificationService.
        self._notif_badge = QLabel("")
        self._notif_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notif_badge.setStyleSheet(
            "QLabel {"
            "  background: rgba(201, 119, 45, 80);"
            "  color: #ffce99;"
            "  font-size: 9px; font-weight: 700;"
            "  padding: 1px 6px; border-radius: 7px;"
            "}"
        )
        self._notif_badge.setToolTip("Notificações pendentes neste workspace")
        self._notif_badge.hide()
        row.addWidget(self._notif_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Pin indicator — aparece à direita do nome quando pinned=True.
        # Empurra os botões de ação pro fim, junto da borda direita.
        from PySide6.QtCore import QSize

        from .icons import ICONS, ic
        self._pin_icon = QLabel()
        self._pin_icon.setFixedSize(14, 14)
        self._pin_icon.setPixmap(
            ic(ICONS["pin"], color="#9aa0a6").pixmap(QSize(12, 12))
        )
        self._pin_icon.setToolTip("Workspace fixado")
        self._pin_icon.hide()
        row.addWidget(self._pin_icon, 0, Qt.AlignmentFlag.AlignVCenter)

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

        self._collapse_btn = QPushButton("⌄")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setToolTip("Recolher / expandir os consoles deste workspace")
        self._collapse_btn.setStyleSheet(_BTN_QSS)
        self._collapse_btn.clicked.connect(on_toggle_collapse)
        row.addWidget(self._collapse_btn)

    def set_label(self, label: str) -> None:
        self._label.setText(label)

    def set_unread_count(self, count: int) -> None:
        """Pinta badge laranja com nº de notificações pendentes — esconde se 0."""
        if count <= 0:
            self._notif_badge.hide()
            return
        self._notif_badge.setText(str(count) if count < 100 else "99+")
        self._notif_badge.show()

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

    def set_pinned(self, pinned: bool) -> None:
        """Mostra/esconde o indicador 📌 ao lado do nome."""
        self._pin_icon.setVisible(pinned)

    def set_selected(self, selected: bool) -> None:
        """Workspace selecionado fica branco; os demais ficam cinza
        claro — visual de "seleção" sem precisar de fundo/borda."""
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_label_color()

    def _apply_label_color(self) -> None:
        from .icons import ic as _ic
        color = "#ffffff" if self._selected else "#9a9a9a"
        self._label.setStyleSheet(f"color: {color};")
        icon_color = (
            self._ws_icon_color_selected
            if self._selected
            else self._ws_icon_color_unselected
        )
        self._ws_icon.setPixmap(
            _ic("fa5s.folder", color=icon_color).pixmap(self._ws_icon_size)
        )

    def set_collapsed(self, collapsed: bool) -> None:
        """Atualiza o ícone do botão de colapsar pra refletir o estado
        atual do tree item (› recolhido, ⌄ expandido). Chevrons em vez
        de triângulos pra não parecerem botão de play."""
        self._collapse_btn.setText("›" if collapsed else "⌄")
