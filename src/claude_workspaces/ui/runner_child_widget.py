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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
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


class RunnerChildWidget(QWidget):
    """Linha compacta de runner na sidebar (filho de workspace)."""

    def __init__(
        self,
        name: str,
        on_toggle: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(22)
        self.setMaximumHeight(22)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
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
            f"color: {theme.TEXT_FAINT}; font-size: 10px;"
        )
        self._addr_label.setVisible(False)
        row.addWidget(self._addr_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._toggle_btn = QPushButton("▶")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFixedSize(20, 18)
        self._toggle_btn.setStyleSheet(_BTN_QSS)
        self._toggle_btn.setToolTip("Iniciar runner")
        self._toggle_btn.clicked.connect(lambda _=False: on_toggle())
        row.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

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
            self._addr_label.setToolTip(url)
            self._addr_label.setVisible(True)
        else:
            self._addr_label.setText("")
            self._addr_label.setToolTip("")
            self._addr_label.setVisible(False)

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
