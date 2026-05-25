"""Visualizador de diff lado-a-lado (side-by-side) estilo IntelliJ.

Mostra o conteúdo antigo (base) à esquerda e o novo (HEAD) à direita,
alinhados linha-a-linha via difflib, com fundo colorido por tipo de mudança
(removido / adicionado / alterado) e scroll vertical sincronizado.

Recebe a lista ordenada de arquivos a inspecionar e um índice inicial; as
setas da toolbar (Shift+F7 / F7) navegam entre as diferenças e, ao chegar no
fim/início, pulam pro próximo/anterior arquivo.
"""

from __future__ import annotations

import difflib
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
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

from ..git_actions import WORKTREE, file_blob
from . import theme

# Fundos por tipo de linha (sutis, sobre o #0e0e0e do editor).
_BG_DEL = QColor("#3a2326")   # removida (esquerda)
_BG_INS = QColor("#22331f")   # adicionada (direita)
_BG_CHG = QColor("#2b2f1e")   # alterada (ambos os lados)
_BG_GAP = QColor("#141414")   # preenchimento de alinhamento

# Realce do trecho que de fato mudou dentro da linha (word-level), mais forte
# que o fundo da linha — como no IntelliJ.
_BG_DEL_STRONG = QColor("#6e2f33")
_BG_INS_STRONG = QColor("#36572b")

# Largura do prefixo de numeração: "{n:>5}  " = 5 dígitos + 2 espaços.
_NUM_PREFIX = 7


class DiffViewerDialog(QDialog):
    """Diff de arquivos lado-a-lado, com navegação entre diferenças/arquivos.

    `files` é uma lista de dicts {folder, base, head, path}; `index` é o
    arquivo inicial a mostrar.
    """

    def __init__(
        self,
        files: list[dict],
        index: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._files = files
        self._idx = max(0, min(index, len(files) - 1)) if files else 0
        self._hunks: list[int] = []   # bloco inicial de cada diferença
        self._cur_hunk: int = -1
        self.setMinimumSize(940, 580)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.BG_PANEL}; color: #e6e6e6; }}"
            "QLabel { color: #cdd3da; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        outer.addLayout(self._build_toolbar())

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

        self._sync_scrollbars()
        self._load_current(goto="first")

        QShortcut(QKeySequence("F7"), self, activated=self._next_diff)
        QShortcut(QKeySequence("Shift+F7"), self, activated=self._prev_diff)

    # ---------- toolbar ----------

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self._prev_btn = QPushButton("▲")
        self._prev_btn.setToolTip("Diferença anterior (Shift+F7)")
        self._prev_btn.setStyleSheet(_TOOL_QSS)
        self._prev_btn.clicked.connect(self._prev_diff)
        row.addWidget(self._prev_btn)

        self._next_btn = QPushButton("▼")
        self._next_btn.setToolTip("Próxima diferença / próximo arquivo (F7)")
        self._next_btn.setStyleSheet(_TOOL_QSS)
        self._next_btn.clicked.connect(self._next_diff)
        row.addWidget(self._next_btn)

        self._title = QLabel("")
        self._title.setStyleSheet("font-size: 12px; font-weight: 600;")
        row.addWidget(self._title)

        row.addStretch()

        self._info = QLabel("")
        self._info.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(self._info)
        return row

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

    # ---------- carregar arquivo ----------

    def _load_current(self, goto: str = "first") -> None:
        """Renderiza o arquivo de índice atual. `goto` = 'first'|'last'
        posiciona na primeira/última diferença."""
        data = self._files[self._idx]
        path = data["path"]
        base, head = data["base"], data["head"]
        self.setWindowTitle(path)
        self._title.setText(path.rsplit("/", 1)[-1])
        self._title.setToolTip(path)

        old_text = file_blob(data["folder"], base, path)
        new_text = file_blob(data["folder"], head, path)
        n_diffs = self._render(old_text, new_text)

        n_files = len(self._files)
        bl = "HEAD" if base == "HEAD" else (base[:7] if base else "base")
        hl = "working" if head == WORKTREE else "HEAD"
        diff_word = "diferença" if n_diffs == 1 else "diferenças"
        self._info.setText(
            f"arquivo {self._idx + 1}/{n_files}  ·  {n_diffs} {diff_word}  ·  "
            f"{bl} → {hl}"
        )
        self._prev_btn.setEnabled(self._idx > 0 or bool(self._hunks))
        self._next_btn.setEnabled(
            self._idx < n_files - 1 or bool(self._hunks)
        )

        if not self._hunks:
            self._cur_hunk = -1
            return
        if goto == "last":
            self._cur_hunk = len(self._hunks) - 1
        else:
            self._cur_hunk = 0
        self._scroll_to_hunk(self._cur_hunk)

    # ---------- navegação ----------

    def _next_diff(self) -> None:
        if self._hunks and self._cur_hunk < len(self._hunks) - 1:
            self._cur_hunk += 1
            self._scroll_to_hunk(self._cur_hunk)
        elif self._idx < len(self._files) - 1:
            self._idx += 1
            self._load_current(goto="first")

    def _prev_diff(self) -> None:
        if self._hunks and self._cur_hunk > 0:
            self._cur_hunk -= 1
            self._scroll_to_hunk(self._cur_hunk)
        elif self._idx > 0:
            self._idx -= 1
            self._load_current(goto="last")

    def _scroll_to_hunk(self, i: int) -> None:
        if not (0 <= i < len(self._hunks)):
            return
        block_no = self._hunks[i]
        for ed in (self._left, self._right):
            doc = ed.document()
            block = doc.findBlockByNumber(block_no)
            if block.isValid():
                cur = QTextCursor(block)
                ed.setTextCursor(cur)
                ed.centerCursor()

    # ---------- alinhamento + render ----------

    def _render(self, old: str, new: str) -> int:
        """Renderiza os dois lados e devolve o nº de diferenças (hunks).

        Cada linha vira (texto, fundo, ranges_intra) — `ranges_intra` é a lista
        de (início, fim) em caracteres do conteúdo que mudou, realçada por cima
        do fundo da linha (word-level diff)."""
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)

        Row = tuple  # (str|None, QColor|None, list[tuple[int,int]])
        left: list[Row] = []
        right: list[Row] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    left.append((old_lines[i1 + k], None, []))
                    right.append((new_lines[j1 + k], None, []))
            elif tag == "delete":
                for k in range(i1, i2):
                    left.append((old_lines[k], _BG_DEL, []))
                    right.append((None, _BG_GAP, []))
            elif tag == "insert":
                for k in range(j1, j2):
                    left.append((None, _BG_GAP, []))
                    right.append((new_lines[k], _BG_INS, []))
            else:  # replace
                n = max(i2 - i1, j2 - j1)
                for k in range(n):
                    lo = old_lines[i1 + k] if i1 + k < i2 else None
                    ne = new_lines[j1 + k] if j1 + k < j2 else None
                    # Quando há par velho/novo, calcula o diff char-a-char pra
                    # realçar só o que mudou dentro da linha.
                    lo_r, ne_r = ([], [])
                    if lo is not None and ne is not None:
                        lo_r, ne_r = _intra_ranges(lo, ne)
                    left.append(
                        (lo, _BG_CHG if lo is not None else _BG_GAP, lo_r)
                    )
                    right.append(
                        (ne, _BG_CHG if ne is not None else _BG_GAP, ne_r)
                    )

        self._fill_pane(self._left, left, _BG_DEL_STRONG)
        self._fill_pane(self._right, right, _BG_INS_STRONG)

        # Hunks = runs de linhas alteradas (qualquer lado com fundo != None).
        self._hunks = []
        in_hunk = False
        for idx in range(len(left)):
            changed = left[idx][1] is not None or right[idx][1] is not None
            if changed and not in_hunk:
                self._hunks.append(idx)
                in_hunk = True
            elif not changed:
                in_hunk = False
        return len(self._hunks)

    def _fill_pane(
        self, ed: QPlainTextEdit, rows: list, strong_bg: QColor
    ) -> None:
        # Linhas com numeração à esquerda; gaps viram linha vazia. Mantém os
        # dois lados com a mesma altura total pro scroll casar.
        text_lines = []
        lineno = 0
        for content, _bg, _intra in rows:
            if content is None:
                text_lines.append("")
            else:
                lineno += 1
                text_lines.append(f"{lineno:>5}  {content}")
        ed.setPlainText("\n".join(text_lines))

        line_sels = []   # fundo da linha inteira
        word_sels = []   # realce das palavras alteradas (pintado por cima)
        doc = ed.document()
        for idx, (_content, bg, intra) in enumerate(rows):
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
            sel.cursor = QTextCursor(block)
            line_sels.append(sel)

            for start, end in intra:
                wsel = QTextEdit.ExtraSelection()
                wfmt = QTextCharFormat()
                wfmt.setBackground(strong_bg)
                wsel.format = wfmt
                cur = QTextCursor(block)
                base = block.position() + _NUM_PREFIX
                cur.setPosition(base + start)
                cur.setPosition(
                    base + end, QTextCursor.MoveMode.KeepAnchor
                )
                wsel.cursor = cur
                word_sels.append(wsel)
        # Linha primeiro, palavras depois — as últimas pintam por cima.
        ed.setExtraSelections(line_sels + word_sels)

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


_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]", re.UNICODE)


def _tokenize(s: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Quebra a linha em tokens (palavra / espaços / pontuação) preservando
    o span (início, fim) de cada um — granularidade de 'Highlight words'."""
    toks: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _TOKEN_RE.finditer(s):
        toks.append(m.group())
        spans.append((m.start(), m.end()))
    return toks, spans


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Funde ranges de char adjacentes/sobrepostos."""
    if not ranges:
        return []
    ranges.sort()
    out = [ranges[0]]
    for s, e in ranges[1:]:
        if s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _intra_ranges(
    old: str, new: str
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Ranges de caractere alterados em cada lado, por palavra.

    Tokeniza ambas as linhas e roda o diff sobre os tokens; tokens que não
    casam (replace/delete/insert) viram ranges de char no lado correspondente.
    """
    o_toks, o_spans = _tokenize(old)
    n_toks, n_spans = _tokenize(new)
    sm = difflib.SequenceMatcher(None, o_toks, n_toks, autojunk=False)
    old_r: list[tuple[int, int]] = []
    new_r: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:  # tokens alterados/removidos no lado velho
            old_r.append((o_spans[i1][0], o_spans[i2 - 1][1]))
        if j2 > j1:  # tokens alterados/adicionados no lado novo
            new_r.append((n_spans[j1][0], n_spans[j2 - 1][1]))
    return _merge(old_r), _merge(new_r)


_GHOST_QSS = (
    "QPushButton {"
    "  background: #1f1f1f; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 4px; padding: 5px 16px;"
    "}"
    "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
)
_TOOL_QSS = (
    "QPushButton {"
    "  background: #1f1f1f; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 4px;"
    "  padding: 2px 10px; font-size: 13px;"
    "}"
    "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
    "QPushButton:disabled { color: #555; border-color: #232323; }"
)
