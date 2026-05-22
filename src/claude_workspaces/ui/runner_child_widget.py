"""Widget custom pros children "runner" da sidebar — uma linha compacta
por runner do workspace, com nome + host:port + estado + botão ▶/■.

    [●]  runner-name  host:port    [▶]

Estados:
    idle/exited → bolinha cinza, botão ▶
    running     → bolinha verde, botão ■
    error       → bolinha vermelha, botão ▶

O host:port só aparece quando há URL conhecida (detectada na saída ou
configurada em `browser_url`). Vazio = label oculta.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

_STATE_COLOR = {
    "idle": theme.TEXT_DISABLED,
    "exited": theme.TEXT_DISABLED,
    "running": theme.SUCCESS,
    "error": theme.DANGER,
}

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


_ROW_QSS = (
    f"QWidget#RunnerChildRow {{"
    f"  background: {theme.BG_DEEP};"
    f"  border: 1px solid {theme.BORDER_SOFT};"
    f"  border-left: 2px solid {theme.BORDER};"
    f"  border-radius: {theme.RADIUS_SM}px;"
    f"}}"
)


class RunnerChildWidget(QWidget):
    """Linha compacta de runner na sidebar (filho de workspace).

    Layout:
        Linha 1: [●] ⚙ nome host:port [▶]
        Linha 2 (opcional): status curto (ex.: "reiniciando"), só aparece
            quando set_status() recebe texto não vazio. Emite size_hint_changed
            pra MainWindow reajustar o sizeHint do QTreeWidgetItem.
    """

    _ROW1_HEIGHT = 18
    _ROW2_HEIGHT = 12

    size_hint_changed = Signal(int)

    def __init__(
        self,
        name: str,
        on_toggle: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._ROW1_HEIGHT)
        self.setMaximumHeight(self._ROW1_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row_widget = QWidget(self)
        row_widget.setObjectName("RunnerChildRow")
        row_widget.setStyleSheet(_ROW_QSS)
        row_widget.setFixedHeight(self._ROW1_HEIGHT)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(6, 0, 4, 0)
        row.setSpacing(6)

        self._dot = QLabel("")
        self._dot.setFixedSize(8, 8)
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._icon = QLabel("⚙")
        self._icon.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px;"
        )
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 11px;"
        )
        self._name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        row.addWidget(self._name_label, stretch=1)

        self._addr_label = QLabel("")
        self._addr_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; font-size: 10px; }}"
            f"QLabel:hover {{ color: {theme.TEXT_LINK}; "
            f"text-decoration: underline; }}"
        )
        self._addr_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._addr_label.setVisible(False)
        self._addr_url: str = ""
        self._addr_label.mousePressEvent = self._on_addr_clicked  # type: ignore[assignment]
        row.addWidget(self._addr_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._toggle_btn = QPushButton("▶")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFixedSize(20, 18)
        self._toggle_btn.setStyleSheet(_BTN_QSS)
        self._toggle_btn.setToolTip("Iniciar runner")
        self._toggle_btn.clicked.connect(lambda _=False: on_toggle())
        row.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(row_widget)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px;"
            "padding: 0px 0px 2px 22px;"
        )
        self._status_label.setVisible(False)
        outer.addWidget(self._status_label)

        self._state = "idle"
        self._apply_state()

    def set_name(self, name: str) -> None:
        self._name_label.setText(name)
        self.setToolTip(name)

    def set_url(self, url: str) -> None:
        """Mostra host:port a partir de uma URL. Vazio = esconde a label."""
        url = (url or "").strip()
        addr = _host_port(url)
        if addr:
            self._addr_label.setText(addr)
            self._addr_label.setToolTip(f"Abrir {url} no navegador")
            self._addr_label.setVisible(True)
            self._addr_url = url if "://" in url else f"http://{url}"
        else:
            self._addr_label.setText("")
            self._addr_label.setToolTip("")
            self._addr_label.setVisible(False)
            self._addr_url = ""

    def _on_addr_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._addr_url:
            return
        from ..errors import LaunchError
        from ..services.system_open import open_url
        try:
            open_url(self._addr_url)
        except LaunchError:
            pass

    def set_status(self, status: str) -> None:
        """Mostra a fase atual (linha 2) só durante transições.

        Só faz sentido visualizar fases transientes (reiniciando, parando,
        carregando) — estados estáveis (rodando, parado, erro) já são
        cobertos pela bolinha colorida na linha 1.
        """
        status = (status or "").strip().lower()
        transient = {"reiniciando", "parando", "carregando"}
        show = status in transient
        was_visible = self._status_label.isVisible()
        if show:
            self._status_label.setText(status)
            self._status_label.setVisible(True)
            target = self._ROW1_HEIGHT + self._ROW2_HEIGHT
        else:
            self._status_label.clear()
            self._status_label.setVisible(False)
            target = self._ROW1_HEIGHT
        self.setMinimumHeight(target)
        self.setMaximumHeight(target)
        if was_visible != show:
            self.size_hint_changed.emit(target)

    def preferred_height(self) -> int:
        return self.maximumHeight()

    def set_state(self, state: str) -> None:
        self._state = state if state in _STATE_COLOR else "idle"
        self._apply_state()

    def _apply_state(self) -> None:
        color = _STATE_COLOR.get(self._state, theme.TEXT_DISABLED)
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;"
        )
        if self._state == "running":
            self._toggle_btn.setText("■")
            self._toggle_btn.setToolTip("Parar runner")
        else:
            self._toggle_btn.setText("▶")
            self._toggle_btn.setToolTip("Iniciar runner")


def _host_port(url: str) -> str:
    """Extrai 'host:port' (ou só 'host') de uma URL. Aceita URLs sem
    esquema fazendo um fallback simples."""
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or ""
    if not host:
        return ""
    port = parsed.port
    if port:
        return f"{host}:{port}"
    return host
