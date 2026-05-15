"""Editor da memória do workspace — o CLAUDE.md da pasta primária.

Claude Code já carrega esse arquivo automaticamente quando inicia
naquele cwd. Aqui só damos uma UI ergonômica pra editar/salvar sem
abrir o IDE.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace

log = logging.getLogger(__name__)


class MemoryPanel(QWidget):
    """Edita o CLAUDE.md da pasta primária do workspace."""

    saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._current_path: Path | None = None
        self._original_text: str = ""
        self._dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        self._path_label = QLabel("(sem workspace)")
        self._path_label.setStyleSheet(
            "color: #b0b0b0; font-size: 11px; font-family: monospace;"
        )
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header.addWidget(self._path_label, stretch=1)
        outer.addLayout(header)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(
            "Convenções, decisões arquiteturais, padrões — qualquer coisa que "
            "o Claude deve saber sempre que rodar aqui. Salvo no CLAUDE.md "
            "da pasta primária, auto-carregado a cada nova sessão."
        )
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(mono)
        self._editor.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6; padding: 6px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        self._editor.textChanged.connect(self._on_text_changed)
        outer.addWidget(self._editor, stretch=1)

        footer = QHBoxLayout()
        self._status = QLabel("")
        self._status.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        footer.addWidget(self._status, stretch=1)
        self._save_btn = QPushButton("Salvar")
        self._save_btn.setStyleSheet(
            "QPushButton {"
            "  background: #3d6ea8; color: #fff;"
            "  border: 0; border-radius: 4px; padding: 4px 14px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a82c5; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        footer.addWidget(self._save_btn)
        outer.addLayout(footer)

        # Auto-save debounced (3s) — opcional, só salva se dirty
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(3000)
        self._autosave_timer.timeout.connect(self._autosave)

    def set_workspace(self, workspace: Workspace | None) -> None:
        # Se há mudança não salva, oferece salvar antes de trocar
        if self._dirty and self._current_path:
            self._save(silent=True)

        self.workspace = workspace
        if not workspace or not workspace.folders:
            self._current_path = None
            self._editor.blockSignals(True)
            self._editor.setPlainText("")
            self._editor.blockSignals(False)
            self._path_label.setText("(workspace sem pastas)")
            self._editor.setReadOnly(True)
            self._save_btn.setEnabled(False)
            self._status.setText("")
            self._dirty = False
            self._original_text = ""
            return

        primary = Path(workspace.folders[0])
        self._current_path = primary / "CLAUDE.md"
        self._path_label.setText(str(self._current_path))
        self._editor.setReadOnly(False)
        self._load()

    def _load(self) -> None:
        if not self._current_path:
            return
        text = ""
        if self._current_path.exists():
            try:
                text = self._current_path.read_text(encoding="utf-8")
            except OSError as e:
                log.warning("erro lendo %s: %s", self._current_path, e)
                self._status.setText(f"(erro lendo: {e})")
                return
        self._editor.blockSignals(True)
        self._editor.setPlainText(text)
        self._editor.blockSignals(False)
        self._original_text = text
        self._dirty = False
        self._save_btn.setEnabled(False)
        if self._current_path.exists():
            self._status.setText("✓ salvo")
        else:
            self._status.setText("(arquivo não existe ainda)")

    def _on_text_changed(self) -> None:
        if not self._current_path:
            return
        current = self._editor.toPlainText()
        self._dirty = current != self._original_text
        self._save_btn.setEnabled(self._dirty)
        if self._dirty:
            self._status.setText("• modificado")
            self._autosave_timer.start()
        else:
            self._status.setText("✓ salvo")

    def _autosave(self) -> None:
        if self._dirty and self._current_path:
            self._save(silent=True)

    def _save(self, silent: bool = False) -> None:
        if not self._current_path:
            return
        text = self._editor.toPlainText()
        try:
            self._current_path.parent.mkdir(parents=True, exist_ok=True)
            self._current_path.write_text(text, encoding="utf-8")
        except OSError as e:
            if not silent:
                QMessageBox.critical(self, "Erro ao salvar", str(e))
            self._status.setText(f"(erro: {e})")
            return
        self._original_text = text
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._status.setText("✓ salvo")
        self.saved.emit()
