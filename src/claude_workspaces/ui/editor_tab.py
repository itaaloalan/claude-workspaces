"""EditorTab — viewer simples de arquivo texto pra abrir como aba central.

Lê o conteúdo do arquivo e exibe em `QPlainTextEdit` read-only com fonte
monospace e wrap desligado. Limita tamanho pra não travar a UI com
arquivos gigantes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

# Limite por arquivo — acima disso só mostra um aviso pra evitar congelar
# a UI carregando MB de log.
_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB


class EditorTab(QWidget):
    """Aba simples de viewer pra um arquivo texto. Read-only."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self.editor.setFont(font)
        self.editor.setStyleSheet(
            "QPlainTextEdit { background: #181818; color: #e6e6e6; "
            "border: 0; selection-background-color: #3d6ea8; }"
        )
        layout.addWidget(self.editor)

        self._load()

    @property
    def path(self) -> str:
        return self._path

    def _load(self) -> None:
        p = Path(self._path)
        try:
            size = p.stat().st_size
        except OSError as e:
            self.editor.setPlainText(f"<falha ao acessar {self._path}: {e}>")
            return
        if size > _MAX_BYTES:
            self.editor.setPlainText(
                f"<arquivo muito grande ({size / 1024 / 1024:.1f} MiB) — "
                f"viewer suporta até {_MAX_BYTES // 1024 // 1024} MiB>"
            )
            return
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.editor.setPlainText(f"<falha ao ler {self._path}: {e}>")
            return
        self.editor.setPlainText(text)
        # Cursor no topo
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)
