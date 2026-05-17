"""TerminalPaneBuilder — constrói o pane do terminal embutido.

Antes era um método `_build_terminal_pane` de ~70 linhas no main_window.
Vive aqui isolado pra simplificar leitura e abrir caminho pra testes
isolados de UI (renderização do header, botões, etc.).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class TerminalPaneBuilder:
    """Constrói o painel do terminal (header com botões + host stack).

    O builder expõe os widgets que a MainWindow precisa wirar:
    - `pane`: QWidget root pra inserir no splitter
    - `header`: QWidget do header (clicado expande quando minimizado)
    - `host`: QStackedWidget que recebe as TerminalAreas
    - `empty_label`: label-placeholder mostrado quando não há aba aberta
    - `placeholder_idx`: índice do empty_label no host
    - `min_btn`, `max_btn`, `restore_btn`: botões de controle de layout
    """

    def __init__(
        self,
        on_min_click: Callable[[], None],
        on_max_click: Callable[[], None],
        on_restore_click: Callable[[], None],
        on_header_click: Callable[[], None],
    ) -> None:
        self._on_min_click = on_min_click
        self._on_max_click = on_max_click
        self._on_restore_click = on_restore_click
        self._on_header_click = on_header_click

    def build(self) -> TerminalPaneBuilder:
        self.pane = QWidget()
        self.pane.setMinimumHeight(0)
        layout = QVBoxLayout(self.pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QWidget()
        self.header.setStyleSheet(
            "background: #161616; border-bottom: 1px solid #2a2a2a;"
        )
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        # Clique no header (fora dos botões) chama o callback
        self.header.mousePressEvent = lambda _ev: self._on_header_click()  # type: ignore[assignment]

        h = QHBoxLayout(self.header)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)
        title = QLabel("Terminal")
        title.setStyleSheet("color: #888; font-size: 11px;")
        h.addWidget(title)
        h.addStretch()

        btn_css = (
            "QPushButton { background: transparent; color: #aaa; "
            "border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #6aa9e0; border-color: #3d6ea8; }"
            "QPushButton:disabled { color: #444; }"
        )
        # Ícones estilo Windows: minimizar (linha), maximizar (quadrado),
        # restaurar (quadrados sobrepostos)
        self.min_btn = QPushButton("—")
        self.min_btn.setToolTip("Minimizar terminal (Ctrl+J)")
        self.min_btn.setFixedWidth(28)
        self.min_btn.setStyleSheet(btn_css)
        self.min_btn.clicked.connect(self._on_min_click)
        h.addWidget(self.min_btn)

        self.max_btn = QPushButton("▢")
        self.max_btn.setToolTip("Maximizar terminal (esconder conteúdo)")
        self.max_btn.setFixedWidth(28)
        self.max_btn.setStyleSheet(btn_css)
        self.max_btn.clicked.connect(self._on_max_click)
        h.addWidget(self.max_btn)

        self.restore_btn = QPushButton("❐")
        self.restore_btn.setToolTip("Restaurar layout 50/50")
        self.restore_btn.setFixedWidth(28)
        self.restore_btn.setStyleSheet(btn_css)
        self.restore_btn.clicked.connect(self._on_restore_click)
        h.addWidget(self.restore_btn)

        layout.addWidget(self.header)

        self.host = QStackedWidget()
        self.host.setMinimumHeight(0)
        self.empty_label = QLabel(
            "Nenhum terminal aberto — clique em 'Abrir Claude' ou 'Abrir Terminal' "
            "para iniciar uma sessão. Cada workspace tem suas próprias abas."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "background: #0e0e0e; color: #555; padding: 28px;"
        )
        self.placeholder_idx = self.host.addWidget(self.empty_label)
        layout.addWidget(self.host, stretch=1)

        return self
