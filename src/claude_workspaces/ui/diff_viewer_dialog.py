"""Visualizador de diff lado-a-lado (side-by-side) estilo IntelliJ.

Mostra o conteúdo antigo (base) à esquerda e o novo (HEAD) à direita,
alinhados linha-a-linha via difflib, com fundo colorido por tipo de mudança
(removido / adicionado / alterado) e scroll vertical sincronizado.
"""

from __future__ import annotations

import difflib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import file_blob
from . import theme

# Fundos por tipo de linha (sutis, sobre o #0e0e0e do editor).
_BG_DEL = QColor("#3a2326")   # removida (esquerda)
_BG_INS = QColor("#22331f")   # adicionada (direita)
_BG_CHG = QColor("#2b2f1e")   # alterada (ambos os lados)
_BG_GAP = QColor("#141414")   # preenchimento de alinhamento


class DiffViewerDialog(QDialog):
    """Diff de um arquivo entre duas revisões, lado-a-lado."""

    def __init__(
        self,
        folder: str,
        base: str,
        head: str,
        path: str,
        base_label: str = "",
        head_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(path)
        self.setMinimumSize(900, 560)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_PANEL}; color: #e6e6e6; }}"
            "QLabel { color: #cdd3da; }"
        )

        old_text = file_blob(folder, base, path)
        new_text = file_blob(folder, head, path)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        bl = base_label or (base[:7] if base else "—")
        hl = head_label or (head[:7] if head else "HEAD")
        title = QLabel(f"<b>{path}</b>")
        title.setStyleSheet("font-size: 12px;")
        header.addWidget(title)
        header.addStretch()
        revs = QLabel(
            f"<span style='color:{theme.DANGER}'>{bl}</span> → "
            f"<span style='color:{theme.SUCCESS}'>{hl}</span>"
        )
        revs.setStyleSheet("font-size: 11px;")
        header.addWidget(revs)
        outer.addLayout(header)

        self._left = self._make_pane()
        self._right = self._make_pane()
        panes = QHBoxLayout()
        panes.setSpacing(6)
        panes.addWidget(self._left, 1)
        panes.addWidget(self._right, 1)
        outer.addLayout(panes, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton("Fechar")
        close.setStyleSheet(_GHOST_QSS)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

        self._render(old_text, new_text)
        self._sync_scrollbars()

    def _make_pane(self) -> QPlainTextEdit:
        ed = QPlainTextEdit()
        ed.setReadOnly(True)
        ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        ed.setFont(mono)
        ed.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #d0d0d0; padding: 2px;"
            "}"
        )
        return ed

    # ---------- alinhamento + render ----------

    def _render(self, old: str, new: str) -> None:
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)

        left: list[tuple[str | None, QColor | None]] = []
        right: list[tuple[str | None, QColor | None]] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    left.append((old_lines[i1 + k], None))
                    right.append((new_lines[j1 + k], None))
            elif tag == "delete":
                for k in range(i1, i2):
                    left.append((old_lines[k], _BG_DEL))
                    right.append((None, _BG_GAP))
            elif tag == "insert":
                for k in range(j1, j2):
                    left.append((None, _BG_GAP))
                    right.append((new_lines[k], _BG_INS))
            else:  # replace
                n = max(i2 - i1, j2 - j1)
                for k in range(n):
                    lo = old_lines[i1 + k] if i1 + k < i2 else None
                    ne = new_lines[j1 + k] if j1 + k < j2 else None
                    left.append((lo, _BG_CHG if lo is not None else _BG_GAP))
                    right.append((ne, _BG_CHG if ne is not None else _BG_GAP))

        self._fill_pane(self._left, left)
        self._fill_pane(self._right, right)

    def _fill_pane(
        self, ed: QPlainTextEdit, rows: list[tuple[str | None, QColor | None]]
    ) -> None:
        # Linhas com numeração à esquerda; gaps viram linha vazia. Mantém os
        # dois lados com a mesma altura total pro scroll casar.
        text_lines = []
        lineno = 0
        for content, _bg in rows:
            if content is None:
                text_lines.append("")
            else:
                lineno += 1
                text_lines.append(f"{lineno:>5}  {content}")
        ed.setPlainText("\n".join(text_lines))

        selections = []
        doc = ed.document()
        for idx, (_content, bg) in enumerate(rows):
            if bg is None:
                continue
            block = doc.findBlockByNumber(idx)
            if not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(bg)
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.format = fmt
            cur = QTextCursor(block)
            sel.cursor = cur
            selections.append(sel)
        ed.setExtraSelections(selections)

    # ---------- scroll sincronizado ----------

    def _sync_scrollbars(self) -> None:
        lv = self._left.verticalScrollBar()
        rv = self._right.verticalScrollBar()
        lh = self._left.horizontalScrollBar()
        rh = self._right.horizontalScrollBar()
        self._syncing = False

        def mirror(src, dst):
            def _slot(val):
                if self._syncing:
                    return
                self._syncing = True
                dst.setValue(val)
                self._syncing = False
            return _slot

        lv.valueChanged.connect(mirror(lv, rv))
        rv.valueChanged.connect(mirror(rv, lv))
        lh.valueChanged.connect(mirror(lh, rh))
        rh.valueChanged.connect(mirror(rh, lh))


_GHOST_QSS = (
    "QPushButton {"
    "  background: #1f1f1f; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 4px; padding: 5px 16px;"
    "}"
    "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
)
