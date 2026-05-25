"""Dock direito estilo IntelliJ tool window:

- Strip vertical (~32px) sempre visível na borda direita, com um botão
  por painel registrado. Cada botão é um glyph monocromático com
  tooltip mostrando o nome (Skills / Memória / Git).
- Click no botão alterna abertura do painel à esquerda do strip;
  múltiplos podem estar abertos ao mesmo tempo (split vertical).
- Botão "▸" no topo do strip esconde tudo de uma vez (collapse-all).
- Quando todos os painéis fechados, o dock fica só com a largura do
  strip — usuário ganha espaço pro restante da janela, mas continua
  vendo os ícones pra reabrir qualquer painel.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import theme

log = logging.getLogger(__name__)


STRIP_WIDTH = 36

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
    f"  border-right: 2px solid transparent;"
    f"  font-family: {_ICON_FONT_STACK};"
    f"  font-size: 16px;"
    f"  padding: 0;"
    f"  text-align: center;"
    f"}}"
    f"QPushButton:hover {{"
    f"  color: {theme.TEXT_MUTED};"
    f"  background: {theme.BG_SURFACE};"
    f"}}"
    f"QPushButton:checked {{"
    f"  color: {theme.TEXT_LINK};"
    f"  background: {theme.BG_DARKER};"
    f"  border-right: 2px solid {theme.TEXT_LINK};"
    f"}}"
)

_COLLAPSE_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_DISABLED};"
    f"  border: none;"
    f"  font-family: {_ICON_FONT_STACK};"
    f"  font-size: 14px;"
    f"  padding: 0;"
    f"}}"
    f"QPushButton:hover {{"
    f"  color: {theme.TEXT_MUTED};"
    f"  background: {theme.BG_SURFACE};"
    f"}}"
    f"QPushButton:disabled {{"
    f"  color: transparent;"
    f"}}"
)


class PanelFrame(QWidget):
    """Wrapper visual em volta do conteúdo de cada painel no dock direito.

    Layout: header row (título + minimize) + content abaixo. Click no
    minimize emite `minimize_requested` que o RightDock conecta no
    `set_panel_open(panel_id, False)`.
    """

    minimize_requested = Signal()

    def __init__(self, label: str, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.BG_DARKEST};")
        self._content = content

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header — title + minimize
        header = QWidget()
        header.setObjectName("PanelFrameHeader")
        header.setStyleSheet(
            f"QWidget#PanelFrameHeader {{"
            f"  background: {theme.BG_DARKER};"
            f"  border-bottom: 1px solid {theme.BORDER};"
            f"}}"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 4, 4, 4)
        hl.setSpacing(4)

        title_lbl = QLabel(label)
        title_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; "
            f"font-weight: 700; letter-spacing: 0.5px;"
        )
        hl.addWidget(title_lbl, stretch=0)

        # Texto extra ao lado do título (ex.: branch + nº de mudanças do
        # Git). O painel empurra via PanelFrame.set_header_extra(); fica
        # vazio/escondido por padrão. Aproveita o espaço livre do header.
        self._extra_lbl = QLabel("")
        self._extra_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._extra_lbl.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 600;"
        )
        self._extra_lbl.setVisible(False)
        hl.addWidget(self._extra_lbl, stretch=1)

        self._minimize_btn = QPushButton("—")
        self._minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minimize_btn.setFixedSize(20, 18)
        self._minimize_btn.setToolTip(f"Minimizar {label}")
        self._minimize_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {theme.TEXT_FAINT};"
            f"  border: 0; border-radius: 3px; font-size: 14px; padding: 0;"
            f"}}"
            f"QPushButton:hover {{ background: {theme.BG_SURFACE}; "
            f"  color: {theme.TEXT_PRIMARY}; }}"
        )
        self._minimize_btn.clicked.connect(self.minimize_requested.emit)
        hl.addWidget(self._minimize_btn, 0, Qt.AlignmentFlag.AlignRight)

        outer.addWidget(header)
        outer.addWidget(content, stretch=1)

    def set_header_extra(self, text: str) -> None:
        """Mostra texto rico ao lado do título do painel (ex.: branch +
        nº de mudanças). Vazio esconde."""
        self._extra_lbl.setText(text or "")
        self._extra_lbl.setVisible(bool(text))


class PanelStripButton(QPushButton):
    """Botão glyph no strip vertical do RightDock. Tooltip mostra o
    nome completo do painel. `checked` indica painel aberto."""

    def __init__(self, icon: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(icon + _VS15, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(STRIP_WIDTH, 40)
        self.setToolTip(label)
        self.setStyleSheet(_PANEL_BTN_QSS)


class RightDock(QWidget):
    """Dock com tool-strip vertical + splitter de painéis."""

    panel_toggled = Signal(str, bool)  # panel_id, is_open

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panels: dict[str, tuple[PanelStripButton, QWidget]] = {}
        self._panel_order: list[str] = []

        self.setStyleSheet(f"background: {theme.BG_DARKEST};")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Container do conteúdo (splitter vertical entre painéis abertos)
        self._content = QSplitter(Qt.Orientation.Vertical)
        self._content.setChildrenCollapsible(False)
        self._content.setHandleWidth(6)
        self._content.setStyleSheet(
            f"QSplitter::handle {{ background: {theme.BORDER}; }}"
            f"QSplitter::handle:hover {{ background: {theme.PRIMARY}; }}"
        )
        outer.addWidget(self._content, stretch=1)

        # Strip lateral fixo
        self._strip = QWidget()
        self._strip.setFixedWidth(STRIP_WIDTH)
        self._strip.setObjectName("DockStrip")
        self._strip.setStyleSheet(
            f"QWidget#DockStrip {{"
            f"  background: {theme.BG_DARKER};"
            f"  border-left: 1px solid {theme.BORDER};"
            f"}}"
        )
        sv = QVBoxLayout(self._strip)
        sv.setContentsMargins(0, 4, 0, 4)
        sv.setSpacing(2)

        # Botão "esconder tudo" no topo do strip
        self._collapse_btn = QPushButton("▸" + _VS15)
        self._collapse_btn.setFixedSize(STRIP_WIDTH, 26)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setToolTip(
            "Esconder todos os painéis (Ctrl+Shift+B alterna o dock inteiro)"
        )
        self._collapse_btn.setStyleSheet(_COLLAPSE_BTN_QSS)
        self._collapse_btn.clicked.connect(self.collapse_all)
        sv.addWidget(self._collapse_btn)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER}; margin: 2px 6px;")
        sv.addWidget(sep)

        sv.addStretch()
        self._strip_layout = sv
        outer.addWidget(self._strip)

        self._update_size_constraints()

    def add_panel(
        self,
        panel_id: str,
        label: str,
        content: QWidget,
        open_: bool = False,
        icon: str = "",
    ) -> None:
        glyph = icon or "◇"
        btn = PanelStripButton(glyph, label)
        btn.toggled.connect(
            lambda checked, pid=panel_id: self._on_btn_toggled(pid, checked)
        )
        # Insere antes do stretch final
        idx = self._strip_layout.count() - 1
        self._strip_layout.insertWidget(idx, btn)

        # Wrappa o content num PanelFrame com header (título + minimize).
        # O minimize clica em set_panel_open(False) — espelho do botão
        # no strip vertical.
        frame = PanelFrame(label, content)
        frame.minimize_requested.connect(
            lambda pid=panel_id: self.set_panel_open(pid, False)
        )
        # Painéis que expõem `header_summary_changed(str)` (ex.: GitPanel)
        # alimentam o texto extra do header (branch + nº de mudanças).
        sig = getattr(content, "header_summary_changed", None)
        if sig is not None:
            sig.connect(frame.set_header_extra)

        self._panels[panel_id] = (btn, frame)
        self._panel_order.append(panel_id)

        # Pre-adiciona o frame ao splitter (escondido)
        self._content.addWidget(frame)
        frame.setVisible(False)

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

    def collapse_all(self) -> None:
        """Fecha todos os painéis abertos. Strip continua visível."""
        for btn, _ in self._panels.values():
            if btn.isChecked():
                btn.setChecked(False)

    def _on_btn_toggled(self, panel_id: str, checked: bool) -> None:
        if panel_id not in self._panels:
            return
        _, widget = self._panels[panel_id]
        widget.setVisible(checked)
        self._update_size_constraints()
        self.panel_toggled.emit(panel_id, checked)

    def _update_size_constraints(self) -> None:
        any_open = any(btn.isChecked() for btn, _ in self._panels.values())
        self._collapse_btn.setEnabled(any_open)
        if any_open:
            # Permite o user redimensionar; usa um mínimo razoável
            self.setMinimumWidth(STRIP_WIDTH + 220)
            self.setMaximumWidth(16777215)
        else:
            self.setMinimumWidth(STRIP_WIDTH)
            self.setMaximumWidth(STRIP_WIDTH)
