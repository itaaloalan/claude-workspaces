"""StatusBar fina inspirada em IDEs (VSCode/JetBrains).

Segmentos da esquerda pra direita:
  workspace ativo · stack · python ver · MCPs · runners ativos · ...
  ... · encoding · line ending · indent · tarefa IA atual

Os segmentos são atualizados pela MainWindow via setters explícitos.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


_SEG_QSS = (
    "QLabel { color: #c8c8c8; font-size: 11px; padding: 0 8px; }"
    "QLabel:hover { color: #fff; background: #2a2a2a; }"
)

_SEP_QSS = (
    "QFrame { background: #2a2a2a; max-width: 1px; min-width: 1px; }"
)


def _segment(text: str = "", tooltip: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_SEG_QSS)
    lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    if tooltip:
        lbl.setToolTip(tooltip)
    return lbl


class _IconSegment(QWidget):
    """Segmento da status bar com ícone SVG (qtawesome) + texto.

    Expõe `setText` / `setVisible` / `setToolTip` pra ter a mesma API
    do `_segment` (QLabel) — os setters externos do StatusBarWidgets
    funcionam sem mudar.
    """

    def __init__(self, qta_name: str, text: str = "", tooltip: str = "") -> None:
        super().__init__()
        from PySide6.QtCore import QSize

        from .icons import ic
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if tooltip:
            self.setToolTip(tooltip)
        self.setStyleSheet(
            "QWidget { background: transparent; }"
            "QWidget:hover { background: #2a2a2a; }"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(4)
        self._icon = QLabel()
        pix = ic(qta_name, color="#9aa0a6").pixmap(QSize(11, 11))
        self._icon.setPixmap(pix)
        h.addWidget(self._icon)
        self._text = QLabel(text)
        self._text.setStyleSheet("QLabel { color: #c8c8c8; font-size: 11px; background: transparent; }")
        h.addWidget(self._text)

    def setText(self, text: str) -> None:
        self._text.setText(text)

    def setToolTip(self, text: str) -> None:  # type: ignore[override]
        super().setToolTip(text)


def _separator() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet(_SEP_QSS)
    return f


class StatusBarWidgets(QWidget):
    """Container com os segmentos. Vive dentro do QStatusBar (addPermanentWidget)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: #161616;")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(0)

        self.workspace = _IconSegment("fa5s.folder-open", "—", "Workspace ativo")
        self.stack = _IconSegment("fa5s.cube", "", "Stack detectado")
        # Versão real do Python que está rodando o app — útil pra debug.
        py_ver = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.python = _IconSegment("fa5b.python", py_ver, f"Python interpretando o app — {sys.executable}")
        self.mcp = _IconSegment("fa5s.plug", "MCP: —", "MCPs configurados pra este workspace")
        self.runners = _IconSegment("mdi6.source-branch", "Runners: —", "Runners ativos no workspace")
        for w in (self.workspace, _separator(), self.stack, _separator(),
                  self.python, _separator(),
                  self.mcp, _separator(), self.runners):
            h.addWidget(w)

        h.addStretch(1)

        self.encoding = _segment("UTF-8", "Encoding")
        self.line_ending = _segment("LF", "Line ending")
        self.indent = _segment("Spaces: 4", "Indentação")
        self.task = _segment("● Nenhuma tarefa em execução", "Estado da sessão Claude ativa")
        for w in (self.encoding, _separator(), self.line_ending, _separator(),
                  self.indent, _separator(), self.task):
            h.addWidget(w)

    # ---------- setters ----------

    def set_workspace(self, name: str | None) -> None:
        self.workspace.setText(name or "—")

    def set_stack(self, label: str) -> None:
        self.stack.setText(label or "")
        self.stack.setVisible(bool(label))

    def set_mcp(self, count: int) -> None:
        self.mcp.setText(f"MCP: {count} configurado{'s' if count != 1 else ''}")

    def set_runners(self, active: int, total: int) -> None:
        if total == 0:
            self.runners.setText("Runners: —")
        else:
            self.runners.setText(f"Runners: {active}/{total} ativos")

    def set_task(self, text: str, *, working: bool = False) -> None:
        """Atualiza o segmento da direita: tarefa IA atual.
        working=True pinta dot amarelo, senão verde discreto."""
        dot = "●" if working else "○"
        color = "#e5b53b" if working else "#5ac35a"
        self.task.setText(
            f"<span style='color:{color}'>{dot}</span> {text}"
        )
        self.task.setTextFormat(Qt.TextFormat.RichText)
