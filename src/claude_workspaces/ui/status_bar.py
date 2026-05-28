"""StatusBar fina inspirada em IDEs (VSCode/JetBrains).

Segmentos da esquerda pra direita:
  workspace ativo · stack · python ver · MCPs · runners ativos · ...
  ... · encoding · line ending · indent · tarefa IA atual

Os segmentos são atualizados pela MainWindow via setters explícitos.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

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

        self.workspace = _IconSegment("fa5s.folder-open", "—", "Clique pra ir ao workspace ativo na sidebar")
        self.stack = _IconSegment("fa5s.cube", "", "Stack detectado")
        # Versão real do Python que está rodando o app — útil pra debug.
        py_ver = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.python = _IconSegment("fa5b.python", py_ver, f"Python interpretando o app — {sys.executable}")
        self.mcp = _IconSegment("fa5s.plug", "MCP: —", "MCPs configurados pra este workspace")
        self.runners = _IconSegment("mdi6.source-branch", "Runners: —", "Runners ativos no workspace")

        # Segmentos do console selecionado — espelham as infos dinâmicas
        # do card da sidebar: estado (com cor) · modelo · branch git.
        # Ficam ocultos enquanto não há console selecionado.
        self._console_sep = _separator()
        self.console_state = _ClickableLabel("")
        self.console_state.setTextFormat(Qt.TextFormat.RichText)
        self.console_state.setStyleSheet(_SEG_QSS)
        self.console_state.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.console_model = _IconSegment("fa5s.robot", "", "Modelo da sessão IA selecionada")
        self.console_branch = QLabel("")
        self.console_branch.setTextFormat(Qt.TextFormat.RichText)
        self.console_branch.setStyleSheet(_SEG_QSS)
        self.console_branch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        for w in (self.workspace, _separator(), self.stack, _separator(),
                  self.python, _separator(),
                  self.mcp, _separator(), self.runners,
                  self._console_sep, self.console_state,
                  self.console_model, self.console_branch):
            h.addWidget(w)

        self._set_console_visible(False)

        h.addStretch(1)

        self.encoding = _segment("UTF-8", "Encoding")
        self.line_ending = _segment("LF", "Line ending")
        self.indent = _segment("Spaces: 4", "Indentação")
        self.task = _segment("● Nenhuma tarefa em execução", "Estado da sessão IA ativa")
        for w in (self.encoding, _separator(), self.line_ending, _separator(),
                  self.indent, _separator(), self.task):
            h.addWidget(w)

    # ---------- setters ----------

    def set_workspace(self, name: str | None) -> None:
        self.workspace.setText(name or "—")

    def set_stack(self, label: str) -> None:
        self.stack.setText(label or "")
        self.stack.setVisible(bool(label))

    def set_mcp(self, count: int, names: list[str] | None = None) -> None:
        # MCP: cinza quando 0, ciano quando há plugados — facilita
        # confirmar de relance se o workspace tem MCP configurado.
        # O tooltip lista os nomes pra dar pra ver quais sem abrir o diálogo.
        names = names or []
        if names:
            self.mcp.setToolTip("MCPs configurados:\n• " + "\n• ".join(names))
        else:
            self.mcp.setToolTip("MCPs configurados pra este workspace")
        if count <= 0:
            self.mcp.setText("MCP: —")
            self.mcp._text.setStyleSheet(
                "QLabel { color: #9aa0a6; font-size: 11px; background: transparent; }"
            )
        else:
            # Mostra os primeiros nomes inline quando couber; senão só a contagem.
            if names:
                shown = ", ".join(names[:3])
                if len(names) > 3:
                    shown += f" +{len(names) - 3}"
                label = f"MCP: {shown}"
            else:
                label = f"MCP: {count} configurado{'s' if count != 1 else ''}"
            self.mcp.setText(label)
            self.mcp._text.setStyleSheet(
                "QLabel { color: #6cc7ce; font-size: 11px; background: transparent; }"
            )

    def set_runners(self, active: int, total: int) -> None:
        # Runners: cinza sem total, verde se algum ativo, amarelo se há
        # runners configurados mas nenhum rodando.
        if total == 0:
            self.runners.setText("Runners: —")
            color = "#9aa0a6"
        elif active > 0:
            self.runners.setText(f"Runners: {active}/{total} ativos")
            color = "#5ac35a"
        else:
            self.runners.setText(f"Runners: 0/{total} parados")
            color = "#e5b53b"
        self.runners._text.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 11px; background: transparent; }}"
        )

    def _set_console_visible(self, visible: bool) -> None:
        self._console_sep.setVisible(visible)
        self.console_state.setVisible(visible)
        self.console_model.setVisible(visible)
        self.console_branch.setVisible(visible)

    def set_console_info(self, info: dict | None) -> None:
        """Atualiza os segmentos do console selecionado.

        `info` é o dict de `TerminalChildWidget.status_info()`; None
        oculta todos os segmentos.
        """
        if info is None:
            self._set_console_visible(False)
            return
        self._set_console_visible(True)
        # Estado: dot colorido + texto composto (ex.: "Trabalhando · …").
        color = info.get("state_color", "#9aa0a6")
        state_text = info.get("state_text", "")
        title = info.get("title", "")
        prefix = f"<b>{title}</b> · " if title else ""
        # Espelha a mesma linguagem visual da sidebar: lá, o texto do
        # estado herda a cor do `_state_label` (amarelo no Aguardando,
        # etc.), o que faz alertas embutidos no statusline do Claude
        # (ex.: "⚠ Limit reached") se destacarem. Aqui aplicamos a cor
        # do estado ao texto inteiro também, em vez de só ao dot.
        self.console_state.setText(
            f"<span style='color:{color}'>●</span> "
            f"<span style='color:{color}'>{prefix}{state_text}</span>"
        )
        self.console_state.setToolTip(
            f"Console selecionado: {title}" if title else "Console selecionado"
        )
        # Modelo (já vem encurtado de status_info)
        model = info.get("model", "")
        self.console_model.setText(model)
        self.console_model.setVisible(bool(model))
        full = info.get("model_full") or ""
        if full:
            self.console_model.setToolTip(f"Modelo: {full}")
        # Branch + dirty count
        branch = info.get("branch", "")
        modified = int(info.get("modified", 0) or 0)
        if not branch:
            self.console_branch.setText("")
            self.console_branch.setVisible(False)
        else:
            short = branch if len(branch) <= 18 else branch[:17] + "…"
            # Branch sempre em amarelo (mesma linguagem visual do chip
            # de branch no toolbar do git_panel); contador de modified
            # fica num amarelo um pouco mais quente pra contrastar.
            if modified > 0:
                self.console_branch.setText(
                    f"<span style='color:#9aa0a6'>⎇</span> "
                    f"<span style='color:#e5b53b;font-weight:600'>{short}</span>"
                    f"  <span style='color:#ff9d3b'>●{modified}</span>"
                )
                self.console_branch.setToolTip(
                    f"Branch: {branch} — {modified} arquivo(s) modificado(s)"
                )
            else:
                self.console_branch.setText(
                    f"<span style='color:#9aa0a6'>⎇</span> "
                    f"<span style='color:#e5b53b;font-weight:600'>{short}</span> "
                    f"<span style='color:#5ac35a'>✓</span>"
                )
                self.console_branch.setToolTip(
                    f"Branch: {branch} — working tree limpo"
                )
            self.console_branch.setVisible(True)

    def set_task(self, text: str, *, working: bool = False) -> None:
        """Atualiza o segmento da direita: tarefa IA atual.
        working=True pinta dot amarelo, senão verde discreto."""
        dot = "●" if working else "○"
        color = "#e5b53b" if working else "#5ac35a"
        self.task.setText(
            f"<span style='color:{color}'>{dot}</span> {text}"
        )
        self.task.setTextFormat(Qt.TextFormat.RichText)
