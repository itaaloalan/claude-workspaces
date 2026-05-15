from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CollapsiblePanel(QWidget):
    """Painel com header clicável que esconde/mostra o conteúdo.
    Usado pro dock direito (Tarefas + Git colapsáveis)."""

    toggled = Signal(bool)  # True = expandido

    def __init__(
        self,
        title: str,
        content: QWidget,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("CollapsibleHeader")
        header.setStyleSheet(
            "QWidget#CollapsibleHeader {"
            "  background: #1a1a1a; border-top: 1px solid #2a2a2a;"
            "  border-bottom: 1px solid #2a2a2a;"
            "}"
            "QWidget#CollapsibleHeader:hover { background: #1f1f1f; }"
        )
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 4, 6, 4)
        h.setSpacing(6)

        self._arrow = QLabel("▼" if expanded else "▶")
        self._arrow.setFixedWidth(12)
        self._arrow.setStyleSheet("color: #888; font-size: 10px;")
        h.addWidget(self._arrow)

        self._title_label = QLabel(title.upper())
        self._title_label.setStyleSheet(
            "color: #ccc; font-size: 11px; font-weight: 600; "
            "letter-spacing: 0.5px;"
        )
        h.addWidget(self._title_label)

        self._extra_host = QWidget()
        self._extra_layout = QHBoxLayout(self._extra_host)
        self._extra_layout.setContentsMargins(0, 0, 0, 0)
        self._extra_layout.setSpacing(4)
        h.addWidget(self._extra_host, stretch=1)

        h.addStretch()

        self._toggle_btn = QPushButton("—")
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setToolTip("Minimizar / expandir")
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: 0; }"
            "QPushButton:hover { color: #6aa9e0; }"
        )
        self._toggle_btn.clicked.connect(self.toggle)
        h.addWidget(self._toggle_btn)

        # Permite click no header inteiro
        header.mousePressEvent = self._on_header_click
        outer.addWidget(header)

        self._content = content
        outer.addWidget(self._content, stretch=1)
        self._content.setVisible(self._expanded)

    def _on_header_click(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.toggle()

    def add_header_widget(self, w: QWidget) -> None:
        """Adiciona widget extra no header (ex: contador, botão de ação)."""
        self._extra_layout.addWidget(w)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._arrow.setText("▼" if expanded else "▶")
        self._toggle_btn.setText("—" if expanded else "▢")
        self.toggled.emit(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)
