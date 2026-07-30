"""Diff rico (diff2html) num modal grande, com navegação entre arquivos.

O `GitPanel` mostra o mesmo diff embutido num painel estreito; este diálogo
reabre exatamente o mesmo conteúdo (mesma instância de `DiffWebView`, formato
e contexto herdados) numa janela bem maior, com setas (F7/Shift+F7 ou ▲/▼)
pra navegar pelos arquivos da lista de mudanças sem fechar e reabrir.

Ao contrário do `DiffViewerDialog` (side-by-side nativo via difflib), aqui o
conteúdo é sempre recalculado via `get_diff`/`get_diff_range` (unified diff)
e renderizado pelo mesmo webview de diff2html/highlight.js do painel.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..git_status import get_diff, get_diff_range
from . import theme
from .diff_web_view import DiffWebView

_GHOST_QSS = (
    "QPushButton {"
    "  background: #1e1e1e; color: #b8b8b8;"
    "  border: 1px solid #2b2b2b; border-radius: 4px; padding: 5px 16px;"
    "}"
    "QPushButton:hover { border-color: #e6e6e6; color: #cfcfcf; }"
)
_TOOL_QSS = (
    "QPushButton {"
    "  background: #1e1e1e; color: #b8b8b8;"
    "  border: 1px solid #2b2b2b; border-radius: 4px;"
    "  padding: 2px 10px; font-size: 13px;"
    "}"
    "QPushButton:hover { border-color: #e6e6e6; color: #cfcfcf; }"
    "QPushButton:disabled { color: #4f4f4f; border-color: #1f1f1f; }"
)
# Mesmas cores dos toggles do diff_hdr embutido (git_panel.py) — consistência
# visual entre o painel e o modal.
_TOGGLE_QSS = (
    "QPushButton {"
    "  background: transparent; color: #757575;"
    "  border: 1px solid #2b2b2b; border-radius: 4px;"
    "  padding: 2px 10px; font-size: 12px;"
    "}"
    "QPushButton:hover { color: #b8b8b8; border-color: #e6e6e6; }"
    "QPushButton:checked { background: #2e2e2e; color: #e6e6e6; border-color: #e6e6e6; }"
)


class DiffExpandDialog(QDialog):
    """Diff rico (diff2html) grande, com navegação entre arquivos.

    `entries` é uma lista de dicts `{folder, rel_path, staged, merge_base_sha,
    label_suffix}`; `merge_base_sha` vazio usa `get_diff` (modo local),
    preenchido usa `get_diff_range` (modo "comparar com branch base").
    `index` é o arquivo inicial a mostrar.
    """

    def __init__(
        self,
        entries: list[dict],
        index: int = 0,
        output_format: str = "line-by-line",
        context: int = 3,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(False)
        self._entries = entries
        self._idx = max(0, min(index, len(entries) - 1)) if entries else 0
        self._output_format = output_format
        self._context = context

        self.resize(1180, 780)
        self.setMinimumSize(940, 580)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_PANEL}; color: #e6e6e6; }}"
            "QLabel { color: #b8b8b8; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        outer.addLayout(self._build_toolbar())

        self._web = DiffWebView(self)
        outer.addWidget(self._web, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton("Fechar")
        close.setStyleSheet(_GHOST_QSS)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        outer.addLayout(footer)

        QShortcut(QKeySequence("F7"), self, activated=self._next_file)
        QShortcut(QKeySequence("Shift+F7"), self, activated=self._prev_file)
        # Explícito: o QWebEngineView pode engolir o Esc antes do reject()
        # padrão do QDialog quando o foco está no conteúdo web.
        QShortcut(QKeySequence("Escape"), self, activated=self.close)

        self._load_current()

    # ---------- toolbar ----------

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self._prev_btn = QPushButton("▲")
        self._prev_btn.setToolTip("Arquivo anterior (Shift+F7)")
        self._prev_btn.setStyleSheet(_TOOL_QSS)
        self._prev_btn.clicked.connect(self._prev_file)
        row.addWidget(self._prev_btn)

        self._next_btn = QPushButton("▼")
        self._next_btn.setToolTip("Próximo arquivo (F7)")
        self._next_btn.setStyleSheet(_TOOL_QSS)
        self._next_btn.clicked.connect(self._next_file)
        row.addWidget(self._next_btn)

        self._title = QLabel("")
        self._title.setStyleSheet("font-size: 12px; font-weight: 600;")
        row.addWidget(self._title)

        row.addStretch()

        self._inline_btn = QPushButton("Inline")
        self._inline_btn.setCheckable(True)
        self._inline_btn.setStyleSheet(_TOGGLE_QSS)
        self._inline_btn.clicked.connect(lambda: self._set_format("line-by-line"))
        row.addWidget(self._inline_btn)

        self._side_btn = QPushButton("Lado a lado")
        self._side_btn.setCheckable(True)
        self._side_btn.setStyleSheet(_TOGGLE_QSS)
        self._side_btn.clicked.connect(lambda: self._set_format("side-by-side"))
        row.addWidget(self._side_btn)

        self._ctx_btn = QPushButton("Expandir")
        self._ctx_btn.setCheckable(True)
        self._ctx_btn.setChecked(self._context != 3)
        self._ctx_btn.setText("Recolher" if self._context != 3 else "Expandir")
        self._ctx_btn.setToolTip("Mostrar arquivo completo / só hunks")
        self._ctx_btn.setStyleSheet(_TOOL_QSS)
        self._ctx_btn.clicked.connect(self._toggle_context)
        row.addWidget(self._ctx_btn)

        self._info = QLabel("")
        self._info.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px; padding-left: 6px;")
        row.addWidget(self._info)

        self._set_format_buttons(self._output_format)
        return row

    def _set_format_buttons(self, fmt: str) -> None:
        self._inline_btn.setChecked(fmt == "line-by-line")
        self._side_btn.setChecked(fmt == "side-by-side")

    # ---------- navegação ----------

    def _next_file(self) -> None:
        if self._idx < len(self._entries) - 1:
            self._idx += 1
            self._load_current()

    def _prev_file(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self._load_current()

    def _set_format(self, fmt: str) -> None:
        self._output_format = fmt
        self._set_format_buttons(fmt)
        self._web.set_output_format(fmt)

    def _toggle_context(self) -> None:
        if self._ctx_btn.isChecked():
            self._context = 100_000  # arquivo inteiro
            self._ctx_btn.setText("Recolher")
        else:
            self._context = 3
            self._ctx_btn.setText("Expandir")
        self._load_current()

    # ---------- render ----------

    def _load_current(self) -> None:
        if not self._entries:
            self._title.setText("(sem arquivos)")
            self._info.setText("")
            return
        entry = self._entries[self._idx]
        rel = entry["rel_path"]
        merge_base_sha = entry.get("merge_base_sha") or ""
        if merge_base_sha:
            text = get_diff_range(
                entry["folder"], rel, merge_base_sha, context=self._context
            )
        else:
            text = get_diff(
                entry["folder"], rel, staged=entry.get("staged", False),
                context=self._context,
            )
        suffix = entry.get("label_suffix") or ""
        self.setWindowTitle(rel)
        self._title.setText(f"{rel}  {suffix}".rstrip())
        self._title.setToolTip(rel)
        self._info.setText(f"arquivo {self._idx + 1}/{len(self._entries)}")
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        self._web.show_diff(text, name)

        self._prev_btn.setEnabled(self._idx > 0)
        self._next_btn.setEnabled(self._idx < len(self._entries) - 1)
