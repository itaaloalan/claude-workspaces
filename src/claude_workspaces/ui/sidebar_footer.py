"""SidebarFooter — rodapé compacto (28px) com painéis expansíveis.

Substitui os blocos inline de: stats de uso, find-file, MinimizeTray,
botão "+ Novo Workspace" e version label — todos agrupados num rodapé
discreto. Chips no footer abrem painéis acima quando clicados.

API pública compatível com sidebar_builder (reassigned attributes):
  context_status_label       — QLabel com rich text de uso
  context_status_refresh_btn — QPushButton ⟳
  context_status_updated_label — QLabel timestamp
  usage_detail_panel         — proxy: main_window chama setVisible(T/F)
  version_label              — _ClickableLabel
  minimized_tray             — MinimizeTray
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme
from .minimize_tray import MinimizeTray


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _UsageLabel(QLabel):
    """QLabel que atualiza o chip de uso no footer ao receber setText."""

    def __init__(self, chip: QPushButton) -> None:
        super().__init__("")
        self._chip = chip

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        plain = re.sub(r"<[^>]+>", "", text)
        m = re.search(r"cooldown\s+\d+[mh]", plain)
        if m:
            self._chip.setText(m.group(0))
            return
        m = re.search(r"\d+h\s+\d+%", plain)
        if m:
            self._chip.setText(m.group(0))
            return
        m = re.search(r"\d+%", plain)
        if m:
            self._chip.setText(m.group(0))


class _UsageVisibilityProxy(QWidget):
    """Proxy: main_window chama setVisible(True/False) aqui.
    Quando True → mostra chip de uso no footer.
    Quando False → esconde chip e colapsa painel de detalhe."""

    def __init__(self, chip: QPushButton, detail: QWidget) -> None:
        super().__init__()
        self._chip = chip
        self._detail = detail

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        # NÃO chama super() — proxy sem parent apareceria como janela flutuante.
        self._chip.setVisible(visible)
        if not visible:
            self._chip.setChecked(False)
            self._detail.setVisible(False)


_CHIP_QSS = (
    f"QPushButton {{ background: {theme.BG_SURFACE}; "
    f"color: {theme.TEXT_FAINT}; border: 1px solid {theme.BORDER_INPUT}; "
    f"border-radius: 3px; font-size: 9px; font-weight: 600; "
    f"padding: 1px 6px; max-height: 18px; }}"
    f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.TEXT_LINK}; }}"
    f"QPushButton:checked {{ background: {theme.BG_DARKER}; "
    f"border-color: {theme.TEXT_LINK}; color: {theme.TEXT_LINK}; }}"
)

_PANEL_QSS = (
    f"QWidget#FooterPanel {{ background: {theme.BG_PANEL}; "
    f"border-top: 1px solid {theme.BORDER}; }}"
)


class SidebarFooter(QWidget):
    """Rodapé compacto da sidebar com chips e painéis expansíveis."""

    def __init__(
        self,
        on_version_clicked: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_version_clicked = on_version_clicked
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Chip criado antes do painel pra _UsageLabel poder receber a referência.
        self._usage_chip = QPushButton("uso")
        self._usage_chip.setCheckable(True)
        self._usage_chip.setVisible(False)
        self._usage_chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._usage_chip.setToolTip("Ver detalhes de uso do plano Claude")
        self._usage_chip.setStyleSheet(_CHIP_QSS)
        self._usage_chip.clicked.connect(self._toggle_usage)

        # ── Painel: detalhe de uso ──────────────────────────────────────
        self._usage_panel = QWidget()
        self._usage_panel.setObjectName("FooterPanel")
        self._usage_panel.setStyleSheet(_PANEL_QSS)
        self._usage_panel.setVisible(False)
        up_layout = QVBoxLayout(self._usage_panel)
        up_layout.setContentsMargins(8, 6, 8, 4)
        up_layout.setSpacing(2)

        up_row = QHBoxLayout()
        up_row.setContentsMargins(0, 0, 0, 0)
        up_row.setSpacing(6)

        self.context_status_label = _UsageLabel(self._usage_chip)
        self.context_status_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FADED}; font-size: 11px; }}"
        )
        self.context_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.context_status_label.setWordWrap(True)
        up_row.addWidget(self.context_status_label, stretch=1)

        self.context_status_refresh_btn = QPushButton("⟳")
        self.context_status_refresh_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        self.context_status_refresh_btn.setToolTip(
            "Forçar sincronização do uso do plano com /api/oauth/usage"
        )
        self.context_status_refresh_btn.setFlat(True)
        self.context_status_refresh_btn.setFixedSize(20, 20)
        self.context_status_refresh_btn.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_FAINT}; background: transparent; "
            "border: none; font-size: 13px; padding: 0px; }"
            f"QPushButton:hover {{ color: {theme.TEXT_PRIMARY}; }}"
            "QPushButton:disabled { color: #555; }"
        )
        up_row.addWidget(
            self.context_status_refresh_btn,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        up_layout.addLayout(up_row)

        self.context_status_updated_label = QLabel("")
        self.context_status_updated_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_DISABLED}; font-size: 9px; }}"
        )
        self.context_status_updated_label.setVisible(False)
        up_layout.addWidget(self.context_status_updated_label)

        outer.addWidget(self._usage_panel)

        # ── Painel: minimizados ─────────────────────────────────────────
        self._min_panel = QWidget()
        self._min_panel.setObjectName("FooterPanel")
        self._min_panel.setStyleSheet(_PANEL_QSS)
        self._min_panel.setVisible(False)
        mp_layout = QVBoxLayout(self._min_panel)
        mp_layout.setContentsMargins(0, 0, 0, 0)
        mp_layout.setSpacing(0)

        self.minimized_tray = _TrackedMinimizeTray(self._on_min_count_changed)
        mp_layout.addWidget(self.minimized_tray)
        # show() só após addWidget — garante que o widget já tem parent
        # (sem parent, show() abriria como janela top-level)
        self.minimized_tray.show()
        outer.addWidget(self._min_panel)

        # ── Separador ───────────────────────────────────────────────────
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        outer.addWidget(sep)

        # ── Footer bar (sempre visível, 28px) ───────────────────────────
        footer_bar = QWidget()
        footer_bar.setFixedHeight(28)
        footer_bar.setStyleSheet(f"QWidget {{ background: {theme.BG_PANEL}; }}")
        fb = QHBoxLayout(footer_bar)
        fb.setContentsMargins(8, 0, 6, 0)
        fb.setSpacing(4)

        self.version_label = _ClickableLabel(f"v{__version__}  ·  notas")
        self.version_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; font-size: 10px; }}"
            f"QLabel:hover {{ color: {theme.TEXT_LINK}; }}"
        )
        self.version_label.setToolTip(
            "Ver o que mudou nesta versão e o histórico completo"
        )
        self.version_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self._on_version_clicked:
            self.version_label.clicked.connect(self._on_version_clicked)
        fb.addWidget(self.version_label, stretch=1)

        fb.addWidget(self._usage_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self._min_chip = QPushButton("0 min")
        self._min_chip.setCheckable(True)
        self._min_chip.setVisible(False)
        self._min_chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._min_chip.setToolTip("Workspaces minimizados")
        self._min_chip.setStyleSheet(_CHIP_QSS)
        self._min_chip.clicked.connect(self._toggle_min)
        fb.addWidget(self._min_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(footer_bar)

        # Proxy que main_window usa para setVisible no "context container"
        self.usage_detail_panel = _UsageVisibilityProxy(
            self._usage_chip, self._usage_panel
        )

    # ── Slots internos ──────────────────────────────────────────────────

    def _toggle_usage(self, checked: bool) -> None:
        if checked and self._min_panel.isVisible():
            self._min_panel.setVisible(False)
            self._min_chip.setChecked(False)
        self._usage_panel.setVisible(checked)

    def _toggle_min(self, checked: bool) -> None:
        if checked and self._usage_panel.isVisible():
            self._usage_panel.setVisible(False)
            self._usage_chip.setChecked(False)
        self._min_panel.setVisible(checked)

    def _on_min_count_changed(self, count: int) -> None:
        if count:
            self._min_chip.setText(f"{count} min")
            self._min_chip.setVisible(True)
        else:
            self._min_chip.setChecked(False)
            self._min_panel.setVisible(False)
            self._min_chip.setVisible(False)


class _TrackedMinimizeTray(MinimizeTray):
    """MinimizeTray que notifica quando a contagem de chips muda."""

    def __init__(
        self,
        on_count_changed: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_count_changed = on_count_changed

    def _refresh_visibility(self) -> None:
        # Não propaga hide/show — o painel pai controla isso.
        self._on_count_changed(len(self._chips))
