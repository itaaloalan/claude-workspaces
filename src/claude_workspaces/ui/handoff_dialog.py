"""Dialog que monta o briefing pra abrir um novo console do Claude
herdando o contexto de uma sessão anterior. Permite editar antes."""

import logging

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..claude_sessions import ClaudeSession

log = logging.getLogger(__name__)


def _suggested_briefing(session: ClaudeSession) -> str:
    preview = (session.preview or "").strip()
    if not preview:
        preview = "(sem preview)"
    short_id = session.id[:8] if session.id else "?"
    return (
        f"Continuando o trabalho da sessão anterior (#{short_id}).\n\n"
        f"Tarefa original:\n> {preview}\n\n"
        f"Próximo passo: "
    )


class HandoffDialog(QDialog):
    """Pre-popula um briefing pra nova sessão. Caller pega via .briefing()."""

    def __init__(self, session: ClaudeSession, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Handoff pra nova sessão")
        self.resize(680, 420)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        info = QLabel(
            "Briefing a ser enviado como primeira mensagem do novo Claude. "
            "Edite o texto antes de confirmar; o conteúdo também vai pra clipboard "
            "como fallback."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #c8c8c8;")
        v.addWidget(info)

        origin = QLabel(
            f"<b>Origem:</b> <code>{session.origin_cwd}</code>  ·  "
            f"<b>ID:</b> <code>{session.id[:8] if session.id else '?'}</code>"
        )
        origin.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        v.addWidget(origin)

        self._edit = QPlainTextEdit(_suggested_briefing(session))
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._edit.setFont(mono)
        self._edit.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6; padding: 8px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        # Cursor no final pra usuário só digitar o próximo passo
        cursor = self._edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._edit.setTextCursor(cursor)
        v.addWidget(self._edit, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Abrir novo Claude com este briefing"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def briefing(self) -> str:
        return self._edit.toPlainText().strip()
