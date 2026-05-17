"""Dialog para exportar sessão JSONL como markdown.

Antes era um método `_export_session` de ~50 linhas inline no main_window.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..services.session_export import export_to_markdown

log = logging.getLogger(__name__)


def open_session_export_dialog(session, parent: QWidget | None = None) -> None:
    """Abre dialog com preview do markdown + opções de salvar e copiar."""
    try:
        md = export_to_markdown(session.path)
    except Exception:
        log.exception("Falha exportando sessão %s", session.id)
        QMessageBox.warning(
            parent, "Falha", "Não foi possível ler o arquivo da sessão."
        )
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Exportar sessão — {session.id[:8]}")
    dlg.resize(820, 600)
    v = QVBoxLayout(dlg)
    preview = QPlainTextEdit(md)
    preview.setReadOnly(False)
    v.addWidget(preview, stretch=1)

    row = QHBoxLayout()
    copy_btn = QPushButton("Copiar pra clipboard")
    save_btn = QPushButton("Salvar como…")
    close_btn = QPushButton("Fechar")
    row.addWidget(copy_btn)
    row.addWidget(save_btn)
    row.addStretch()
    row.addWidget(close_btn)
    v.addLayout(row)

    copy_btn.clicked.connect(
        lambda: QGuiApplication.clipboard().setText(preview.toPlainText())
    )

    def do_save() -> None:
        default = f"claude-session-{session.id[:8]}.md"
        path, _ = QFileDialog.getSaveFileName(
            dlg, "Salvar markdown", default, "Markdown (*.md);;Todos (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(preview.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(dlg, "Falha ao salvar", str(e))

    save_btn.clicked.connect(do_save)
    close_btn.clicked.connect(dlg.accept)
    dlg.exec()
