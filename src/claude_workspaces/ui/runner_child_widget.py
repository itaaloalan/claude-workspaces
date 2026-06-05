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
    # Flat row: sem borda, só bg sutil. Hover vira um tint mais claro.
    # A borda ao redor de cada item criava poluição visual quando muitos
    # runners estão listados — removida em 0.76.55.
    f"#RunnerCard {{"
    f"  background: transparent;"
    f"  border: 0;"
    f"  border-radius: {theme.RADIUS_MD}px;"
    f"}}"
    f"#RunnerCard:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"}}"
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
        on_restart: Callable[[], None] | None = None,
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
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(0)
        self._card = QFrame()
        self._card.setObjectName("RunnerCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
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
            "QLabel { background: transparent; border: 0; }"
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

        # Chip 📁: aponta o runner pro diretório de um console (worktree).
        # Hover-only, igual aos demais botões de ação.
        self._cwd_btn = QPushButton("📁")
        self._cwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cwd_btn.setFixedSize(24, 24)
        self._cwd_btn.setStyleSheet(_BTN_QSS)
        self._cwd_btn.setToolTip("Apontar o runner pro diretório de um console")
        self._cwd_btn.clicked.connect(self._open_cwd_menu)
        self._cwd_btn.setVisible(False)
        card_layout.addWidget(self._cwd_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._restart_btn = QPushButton("↻")
        self._restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restart_btn.setFixedSize(24, 24)
        self._restart_btn.setStyleSheet(_BTN_QSS)
        self._restart_btn.setToolTip("Reiniciar runner")
        if on_restart is not None:
            self._restart_btn.clicked.connect(lambda _=False: on_restart())
        self._restart_btn.setVisible(False)
        card_layout.addWidget(self._restart_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._toggle_btn = QPushButton("▶")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFixedSize(24, 24)
        self._toggle_btn.setStyleSheet(_BTN_QSS)
        self._toggle_btn.setToolTip("Iniciar runner")
        self._toggle_btn.clicked.connect(lambda _=False: on_toggle())
        # Hidden by default — only visible on hover to reduce visual noise.
        self._toggle_btn.setVisible(False)
        card_layout.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._state = "idle"
        # Cwd efetivo do runner (📁 na linha de status; path no tooltip).
        self._cwd_path: str = ""
        # Porta base do runner (`:8081` na linha de status; 0 = sem porta).
        self._port: int = 0
        self._cwd_options_provider: Callable | None = None
        self._on_cwd_selected: Callable[[str], None] | None = None
        self._has_restart = on_restart is not None
        self._apply_state()

    # ---- hover: show/hide action buttons --------------------------------

    def enterEvent(self, event) -> None:  # noqa: D401
        self._toggle_btn.setVisible(True)
        self._restart_btn.setVisible(self._has_restart)
        self._cwd_btn.setVisible(self._on_cwd_selected is not None)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401
        self._toggle_btn.setVisible(False)
        self._restart_btn.setVisible(False)
        self._cwd_btn.setVisible(False)
        super().leaveEvent(event)

    # ---- cwd (📁) --------------------------------------------------------

    def set_cwd(self, path: str) -> None:
        """Cwd efetivo do runner — mostra `📁 <pasta>` na linha de status e
        o path completo no tooltip do card."""
        self._cwd_path = (path or "").strip()
        self._apply_state()
        self._refresh_tooltip()

    def set_port(self, port: int) -> None:
        """Porta base do runner — mostra `:8081` na linha de status
        (0 = sem porta, sem sufixo)."""
        port = int(port or 0)
        if port == self._port:
            return
        self._port = port
        self._apply_state()

    def set_cwd_menu(
        self,
        provider: Callable,
        on_selected: Callable[[str], None],
    ) -> None:
        """`provider() -> list[(label, path)]` com os diretórios dos consoles
        abertos; `on_selected(path)` aponta o runner ("" = padrão)."""
        self._cwd_options_provider = provider
        self._on_cwd_selected = on_selected

    def _open_cwd_menu(self) -> None:
        if self._on_cwd_selected is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)

        def add_option(label: str, path: str, target: str) -> None:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(bool(path) and path == self._cwd_path)
            act.triggered.connect(
                lambda _=False, t=target: self._on_cwd_selected(t)
            )

        add_option("Padrão do runner", "", "")
        dirs: list[tuple[str, str]] = []
        if self._cwd_options_provider is not None:
            try:
                dirs = list(self._cwd_options_provider() or [])
            except Exception:
                pass
        if dirs:
            menu.addSeparator()
            sec = menu.addAction("Consoles abertos")
            sec.setEnabled(False)
            for label, path in dirs:
                if path:
                    add_option(f"{label}  ({path})", path, path)
        menu.exec(self._cwd_btn.mapToGlobal(self._cwd_btn.rect().bottomLeft()))

    def _refresh_tooltip(self) -> None:
        name = self._name_label.text()
        if self._cwd_path:
            self.setToolTip(f"{name}\nDiretório: {self._cwd_path}")
        else:
            self.setToolTip(name)

    def set_name(self, name: str) -> None:
        self._name_label.setText(name)
        self._refresh_tooltip()

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
            self._status_label.setText(f"●  {text}{self._cwd_suffix()}")
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

    def _cwd_suffix(self) -> str:
        """Sufixo `· :porta · 📁 <pasta>` da linha de status (cada parte
        some quando vazia)."""
        suffix = ""
        if self._port > 0:
            suffix += f"  ·  :{self._port}"
        if self._cwd_path:
            from pathlib import Path
            suffix += f"  ·  📁 {Path(self._cwd_path).name}"
        return suffix

    def _apply_state(self) -> None:
        color = _STATE_COLOR.get(self._state, theme.TEXT_FAINT)
        label = _STATE_LABEL.get(self._state, "Idle")
        # Bolinha colorida no início do status line.
        self._status_label.setText(f"●  {label}{self._cwd_suffix()}")
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
