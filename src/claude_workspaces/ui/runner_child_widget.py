"""Widget custom pros children "runner" da sidebar — um card por runner
do workspace, no estilo do mockup:

    ┌─────────────────────────────────────────────────┐
    │ [📦]  glassfish-ogpms          host:port  [▶] ⋯ │
    │       ● Running                                 │
    └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from PySide6.QtCore import QSize, Qt, Signal
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
    "idle": theme.TEXT_FAINT,
    "exited": theme.TEXT_FAINT,
    "running": theme.SUCCESS,
    "error": theme.DANGER,
}

_STATE_LABEL = {
    "idle": "Idle",
    "exited": "Idle",
    "running": "Running",
    "error": "Failed",
}

_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: {theme.RADIUS_SM}px;"
    f"  padding: 0;"
    f"  font-size: 13px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_PANEL};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)

_CARD_QSS = (
    f"#RunnerCard {{"
    f"  background: #232323;"
    f"  border: 1px solid #333333;"
    f"  border-radius: {theme.RADIUS_MD}px;"
    f"}}"
    # Filhos transparentes — evita QPalette.Window dos QLabels vazar
    # bg cinza escuro sobre o card e criar ilusão de "dois backgrounds".
    f"#RunnerCard QLabel {{ background: transparent; }}"
    f"#RunnerCard QPushButton {{ background: transparent; }}"
    f"#RunnerCard QWidget {{ background: transparent; }}"
)


class RunnerChildWidget(QWidget):
    """Card de runner na sidebar (filho de workspace).

    Layout (~44px):
        Linha 1: [icon]  nome             host:port  [▶/■]  [⋯]
        Linha 2:         status (Running/Idle/Failed)
    """

    _CARD_HEIGHT = 32

    size_hint_changed = Signal(int)

    def __init__(
        self,
        name: str,
        on_toggle: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._CARD_HEIGHT)
        self.setMaximumHeight(self._CARD_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # Wrapper externo transparente com margem horizontal — afasta o
        # card dos limites do workspace card pai. Sem isso o card ficava
        # colado nas paredes do workspace. O conteúdo real vive dentro
        # do `_card` (QFrame com bg/border via #RunnerCard).
        from PySide6.QtWidgets import QFrame
        wrapper = QHBoxLayout(self)
        wrapper.setContentsMargins(8, 0, 8, 0)
        wrapper.setSpacing(0)
        self._card = QFrame()
        self._card.setObjectName("RunnerCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setStyleSheet(_CARD_QSS)
        wrapper.addWidget(self._card)

        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(8, 2, 6, 2)
        card_layout.setSpacing(6)

        # Ícone à esquerda — quadradinho com cube/box (match mockup).
        from .icons import ic as _ic
        self._icon = QLabel()
        self._icon.setFixedSize(20, 20)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet(
            f"QLabel {{ background: {theme.BG_DEEP}; "
            f"border: 1px solid {theme.BORDER_SOFT}; "
            f"border-radius: {theme.RADIUS_SM}px; }}"
        )
        self._icon.setPixmap(
            _ic("mdi6.cube-outline", color=theme.TEXT_FADED).pixmap(QSize(14, 14))
        )
        card_layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        # Bloco central: nome em cima, status embaixo.
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;"
        )
        self._name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        text_col.addWidget(self._name_label)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px;"
        )
        text_col.addWidget(self._status_label)
        card_layout.addLayout(text_col, stretch=1)

        # URL compacta (host:port) — só aparece se houver
        self._addr_label = QLabel("")
        self._addr_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; font-size: 10px; "
            f"padding: 0 4px; }}"
            f"QLabel:hover {{ color: {theme.TEXT_LINK}; "
            f"text-decoration: underline; }}"
        )
        self._addr_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._addr_label.setVisible(False)
        self._addr_url: str = ""
        self._addr_label.mousePressEvent = self._on_addr_clicked  # type: ignore[assignment]
        card_layout.addWidget(self._addr_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._toggle_btn = QPushButton("▶")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.setStyleSheet(_BTN_QSS)
        self._toggle_btn.setToolTip("Iniciar runner")
        self._toggle_btn.clicked.connect(lambda _=False: on_toggle())
        card_layout.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # ⋯ removido por enquanto — não tem ações plumbadas via callback
        # (start/stop/restart/edit/remove vivem no pane Runners, não no
        # widget da sidebar). Voltar a adicionar quando houver hookup.

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
        """Fases transientes (reiniciando, parando, carregando) sobrescrevem
        o label de estado padrão. Estados estáveis ficam na palavra do
        _STATE_LABEL (Running/Idle/Failed) pintada pelo _apply_state."""
        status = (status or "").strip().lower()
        transient = {"reiniciando", "parando", "carregando", "startando"}
        if status in transient:
            # "startando" ganha "..." pra deixar claro que é em andamento
            # (mockup pedido pelo usuário: "Startando..." enquanto o
            # browser não abre).
            text = "Startando..." if status == "startando" else status
            self._status_label.setText(f"●  {text}")
            self._status_label.setStyleSheet(
                f"color: {theme.WARNING}; font-size: 10px;"
            )
        else:
            self._apply_state()  # restaura label/cor padrão

    def preferred_height(self) -> int:
        return self._CARD_HEIGHT

    def set_state(self, state: str) -> None:
        self._state = state if state in _STATE_COLOR else "idle"
        self._apply_state()

    def _apply_state(self) -> None:
        color = _STATE_COLOR.get(self._state, theme.TEXT_FAINT)
        label = _STATE_LABEL.get(self._state, "Idle")
        # Bolinha colorida no início do status line.
        self._status_label.setText(f"●  {label}")
        self._status_label.setStyleSheet(
            f"color: {color}; font-size: 10px;"
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
