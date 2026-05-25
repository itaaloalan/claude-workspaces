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

from PySide6.QtCore import QEvent, Qt
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

# Pill com count quando há >1 terminal rodando — agora via token de estado
# (state_badge_qss) pra ficar consistente com o resto da sidebar.
_BADGE_QSS = theme.state_badge_qss(theme.STATE_DONE)
_NOTIF_BADGE_QSS = theme.state_badge_qss(theme.STATE_AWAITING)


class WorkspaceItemWidget(QWidget):
    """Widget linha pra cada workspace top-level com botões inline."""

    def __init__(
        self,
        name: str,
        on_add_claude: Callable[[], None],
        on_toggle_collapse: Callable[[], None],
        on_toggle_pin: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(38)
        self._on_add_claude = on_add_claude
        self._on_toggle_collapse = on_toggle_collapse
        self._on_toggle_pin = on_toggle_pin
        self._pinned = False
        # Enable hover tracking pro reveal das ações secundárias.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # CRÍTICO: WA_StyledBackground faz o QSS de bg/border renderizar
        # em subclasses de QWidget no PySide6. Sem isso o QSS é ignorado
        # silenciosamente e o card nunca aparece.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("WorkspaceCard")
        # Card visual — bg sólido + borda sutil + radius, igual mockup.
        # Tom muda em set_selected (tint azul) / hover (borda mais clara).
        self._selected = False
        self._apply_card_qss()

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(8)

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
        self._notif_badge.setStyleSheet(_NOTIF_BADGE_QSS)
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
        self._add_btn.setVisible(False)  # reveal on hover
        row.addWidget(self._add_btn)

        self._more_btn = QPushButton("⋯")
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setFixedSize(22, 22)
        self._more_btn.setToolTip("Mais ações")
        self._more_btn.setStyleSheet(_BTN_QSS)
        self._more_btn.clicked.connect(self._open_menu)
        self._more_btn.setVisible(False)  # reveal on hover
        row.addWidget(self._more_btn)

        self._collapse_btn = QPushButton("⌄")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setToolTip("Recolher / expandir os consoles deste workspace")
        self._collapse_btn.setStyleSheet(_BTN_QSS)
        self._collapse_btn.clicked.connect(on_toggle_collapse)
        row.addWidget(self._collapse_btn)

    def _open_menu(self) -> None:
        menu = QMenu(self._more_btn)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.BG_SURFACE}; "
            f"color: {theme.TEXT_PRIMARY}; border: 1px solid {theme.BORDER_INPUT}; }}"
            f"QMenu::item {{ padding: 6px 14px; }}"
            f"QMenu::item:selected {{ background: {theme.PRIMARY}; "
            f"color: {theme.TEXT_BRIGHT}; }}"
        )
        menu.addAction("＋  Abrir Claude novo").triggered.connect(self._on_add_claude)
        menu.addAction("Recolher / expandir").triggered.connect(self._on_toggle_collapse)
        if self._on_toggle_pin is not None:
            menu.addSeparator()
            pin_label = "📌  Desafixar workspace" if self._pinned else "📌  Fixar workspace"
            menu.addAction(pin_label).triggered.connect(self._on_toggle_pin)
        menu.exec_(self._more_btn.mapToGlobal(self._more_btn.rect().bottomRight()))

    def event(self, e: QEvent) -> bool:  # type: ignore[override]
        if e.type() == QEvent.Type.HoverEnter:
            self._add_btn.setVisible(True)
            self._more_btn.setVisible(True)
        elif e.type() == QEvent.Type.HoverLeave:
            self._add_btn.setVisible(False)
            self._more_btn.setVisible(False)
        return super().event(e)

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
        self._pinned = pinned
        self._pin_icon.setVisible(pinned)

    def set_selected(self, selected: bool) -> None:
        """Workspace selecionado ganha tint azul + borda primary; demais
        ficam com bg sutil + borda discreta — visual de card sempre."""
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_label_color()
        self._apply_card_qss()

    def _apply_card_qss(self) -> None:
        """Renderiza o widget como card (bg + borda + radius), igual
        mockup. Quando expandido, achata o canto inferior + remove a
        borda de baixo — assim o card visualmente "continua" descendo
        pra englobar os children (Sessões Claude, Runners, etc)."""
        if self._selected:
            bg = "rgba(61, 110, 168, 38)"
            border = theme.PRIMARY
        else:
            bg = "#232323"
            border = "#333333"
        expanded = getattr(self, "_expanded", False)
        # Quando expandido, zera raio + borda inferior → ilusão de card
        # contínuo descendo pros children. Quando colapsado, card fechado
        # nas 4 quinas.
        if expanded:
            border_radius = (
                "border-top-left-radius: 6px;"
                "border-top-right-radius: 6px;"
                "border-bottom-left-radius: 0px;"
                "border-bottom-right-radius: 0px;"
            )
            border_qss = (
                f"border-top: 1px solid {border};"
                f"border-left: 1px solid {border};"
                f"border-right: 1px solid {border};"
                f"border-bottom: 0;"
            )
        else:
            border_radius = "border-radius: 6px;"
            border_qss = f"border: 1px solid {border};"
        self.setStyleSheet(
            f"#WorkspaceCard {{"
            f"  background: {bg};"
            f"  {border_qss}"
            f"  {border_radius}"
            f"}}"
            f"#WorkspaceCard:hover {{"
            f"  border-color: {theme.PRIMARY_HOVER if self._selected else '#404040'};"
            f"}}"
            # Filhos transparentes — sem isso QLabel/QPushButton/QWidget
            # filhos caem em QPalette.Window e criam quadradinhos de bg
            # diferente sobre o card.
            f"#WorkspaceCard QLabel {{ background: transparent; }}"
            f"#WorkspaceCard QPushButton {{ background: transparent; }}"
            f"#WorkspaceCard QWidget {{ background: transparent; }}"
        )

    def set_expanded_visual(self, expanded: bool) -> None:
        """Avisa o card que o workspace está expandido/colapsado pra ele
        ajustar a borda inferior — efeito 'card contínuo' quando expandido."""
        if getattr(self, "_expanded", False) == expanded:
            return
        self._expanded = expanded
        self._apply_card_qss()

    def _apply_label_color(self) -> None:
        from .icons import ic as _ic
        color = theme.TEXT_PRIMARY if self._selected else theme.TEXT_MUTED
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
