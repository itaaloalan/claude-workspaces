"""Dock direito estilo Orca:

- Row horizontal de ícones no TOPO do painel, um botão por painel
  registrado (checkable, exclusivo — sempre exatamente um ativo).
- Abaixo, um QStackedWidget mostra SÓ o painel ativo — nada de splitter
  empilhado espremendo painéis; trocar de painel é instantâneo e só o
  visível consome refresh (dirty-refresh no DockCoordinator).
- "Esconder tudo" não existe mais como estado interno: esconder =
  alternar o dock inteiro (Ctrl+Shift+B / botão da top bar).
- O texto extra do header (ex.: branch + nº de mudanças do Git) vive à
  direita da própria row, visível quando o painel dono está ativo.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme

log = logging.getLogger(__name__)


TOP_ROW_H = 34
MIN_PANEL_W = 260

# U+FE0E força "text presentation" no glyph anterior — evita render emoji
_VS15 = "︎"

_ICON_FONT_STACK = (
    '"Symbola", "DejaVu Sans Mono", "Noto Sans Symbols 2",'
    ' "Segoe UI Symbol", monospace'
)

_PANEL_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: none;"
    f"  border-bottom: 2px solid transparent;"
    f"  font-family: {_ICON_FONT_STACK};"
    f"  font-size: 15px;"
    f"  padding: 0;"
    f"  text-align: center;"
    f"}}"
    f"QPushButton:hover {{"
    f"  color: {theme.TEXT_MUTED};"
    f"}}"
    f"QPushButton:checked {{"
    f"  color: {theme.TEXT_PRIMARY};"
    f"  border-bottom: 2px solid {theme.PRIMARY};"
    f"}}"
)


class PanelTabButton(QPushButton):
    """Botão de painel na row superior do RightDock. Tooltip mostra o
    nome completo do painel. `checked` indica painel ativo.

    `icon` pode ser nome qtawesome ("ph.git-branch") — detectado pelo
    ponto — ou glyph unicode (fallback como texto)."""

    def __init__(self, icon: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon if "." in icon else None
        if self._icon_name is None:
            self.setText(icon + _VS15)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, TOP_ROW_H)
        self.setToolTip(label)
        self.setStyleSheet(_PANEL_BTN_QSS)
        self._paint_icon()
        self.toggled.connect(lambda _c: self._paint_icon())

    def _paint_icon(self) -> None:
        if self._icon_name is None:
            return
        from PySide6.QtCore import QSize

        from .icons import ic
        color = theme.TEXT_PRIMARY if self.isChecked() else theme.TEXT_FAINT
        self.setIcon(ic(self._icon_name, color=color))
        self.setIconSize(QSize(15, 15))


class RightDock(QWidget):
    """Dock com row de ícones no topo + stack exclusivo de painéis."""

    # Compat histórico: emite (pid, False) pro painel que saiu e
    # (pid, True) pro que entrou. O DockCoordinator só reage ao True.
    panel_toggled = Signal(str, bool)  # panel_id, is_open

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # panel_id -> (botão, content widget)
        self._panels: dict[str, tuple[PanelTabButton, QWidget]] = {}
        self._panel_order: list[str] = []
        self._active_id: str | None = None
        # Texto extra por painel (ex.: git → branch + nº de mudanças);
        # exibido na row quando o painel dono está ativo.
        self._header_extras: dict[str, str] = {}

        self.setStyleSheet(f"background: {theme.BG_DARKEST};")
        self.setMinimumWidth(MIN_PANEL_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Row superior: ícones dos painéis + extra do painel ativo
        top = QWidget()
        top.setFixedHeight(TOP_ROW_H)
        top.setObjectName("DockTopRow")
        top.setStyleSheet(
            f"QWidget#DockTopRow {{"
            f"  background: {theme.BG_DARKER};"
            f"  border-bottom: 1px solid {theme.BORDER};"
            f"}}"
        )
        tl = QHBoxLayout(top)
        tl.setContentsMargins(4, 0, 8, 0)
        tl.setSpacing(2)
        self._top_layout = tl

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        self._extra_lbl = QLabel("")
        self._extra_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._extra_lbl.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_XS}px; font-weight: 600;"
        )
        self._extra_lbl.setVisible(False)
        # stretch + label ficam SEMPRE no fim; botões são inseridos antes.
        tl.addStretch()
        tl.addWidget(self._extra_lbl)

        outer.addWidget(top)

        # Stack exclusivo — um painel visível por vez
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, stretch=1)

    # ------------------------------------------------------------------
    # API pública (compatível com o RightDock antigo)

    def add_panel(
        self,
        panel_id: str,
        label: str,
        content: QWidget,
        open_: bool = False,
        icon: str = "",
    ) -> None:
        glyph = icon or "◇"
        btn = PanelTabButton(glyph, label)
        btn.clicked.connect(lambda _=False, pid=panel_id: self._activate(pid))
        self._btn_group.addButton(btn)
        # Insere antes do stretch final (stretch + extra ficam no fim)
        self._top_layout.insertWidget(len(self._panel_order), btn)

        # Painéis que expõem `header_summary_changed(str)` (ex.: GitPanel)
        # alimentam o texto extra da row (branch + nº de mudanças).
        sig = getattr(content, "header_summary_changed", None)
        if sig is not None:
            sig.connect(
                lambda text, pid=panel_id: self._set_header_extra(pid, text)
            )

        self._panels[panel_id] = (btn, content)
        self._panel_order.append(panel_id)
        self._stack.addWidget(content)

        if open_ or self._active_id is None:
            # Durante o build o 1º painel vira ativo por default; o sinal
            # panel_toggled só interessa em interação real do usuário.
            self._activate(panel_id, initial=self._active_id is None)

    def open_panels(self) -> list[str]:
        return [self._active_id] if self._active_id else []

    def active_panel(self) -> str | None:
        return self._active_id

    def set_panel_open(self, panel_id: str, open_: bool) -> None:
        """Compat: `True` ativa o painel; `False` é ignorado — no modelo
        exclusivo sempre há um painel ativo (esconder = toggle do dock)."""
        if open_ and panel_id in self._panels:
            self._activate(panel_id)

    # ------------------------------------------------------------------

    def _activate(self, panel_id: str, initial: bool = False) -> None:
        if panel_id not in self._panels:
            return
        previous = self._active_id
        if previous == panel_id:
            # QButtonGroup exclusivo permite "des-clicar" visualmente? Não —
            # mas garante o checked de volta caso o clique tenha mexido.
            self._panels[panel_id][0].setChecked(True)
            return
        btn, content = self._panels[panel_id]
        btn.setChecked(True)
        self._stack.setCurrentWidget(content)
        self._active_id = panel_id
        self._refresh_extra()
        if previous is not None:
            self.panel_toggled.emit(previous, False)
        if not initial:
            self.panel_toggled.emit(panel_id, True)

    def _set_header_extra(self, panel_id: str, text: str) -> None:
        self._header_extras[panel_id] = text or ""
        self._refresh_extra()

    def _refresh_extra(self) -> None:
        text = self._header_extras.get(self._active_id or "", "")
        self._extra_lbl.setText(text)
        self._extra_lbl.setVisible(bool(text))
