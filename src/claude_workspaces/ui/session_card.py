from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..claude_sessions import ClaudeSession


class SessionCard(QFrame):
    """Card visual pra uma sessão do Claude. Substitui o item cru de QListWidget."""

    resume_requested = Signal(ClaudeSession)
    delete_requested = Signal(ClaudeSession)

    def __init__(
        self,
        session: ClaudeSession,
        show_origin: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("SessionCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#SessionCard {"
            "  background: #1f1f1f;"
            "  border: 1px solid #2c2c2c;"
            "  border-radius: 8px;"
            "}"
            "QFrame#SessionCard:hover { border-color: #3d6ea8; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)

        title_text = self._title_text()
        title = QLabel(title_text)
        title.setStyleSheet("font-weight: 600; color: #e6e6e6;")
        title.setWordWrap(True)
        header.addWidget(title, stretch=1)

        when = QLabel(self._when_text())
        when.setStyleSheet("color: #a8a8a8; font-size: 11px;")
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(when)

        outer.addLayout(header)

        if show_origin:
            origin = QLabel(Path(session.origin_cwd).name)
            origin.setStyleSheet("color: #6aa9e0; font-size: 11px;")
            outer.addWidget(origin)

        if session.preview:
            preview = QLabel(self._preview_text())
            preview.setStyleSheet("color: #c8c8c8; font-size: 12px;")
            preview.setWordWrap(True)
            outer.addWidget(preview)

        actions = QHBoxLayout()
        actions.addStretch()

        delete_btn = QPushButton("Remover")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setToolTip("Excluir o arquivo desta sessão (.jsonl)")
        delete_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #a8a8a8;"
            "  border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px 10px;"
            "}"
            "QPushButton:hover { color: #e57373; border-color: #a23a3a; }"
        )
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.session))
        actions.addWidget(delete_btn)

        resume_btn = QPushButton("Retomar")
        resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        resume_btn.setStyleSheet(
            "QPushButton {"
            "  background: #2d4a6e; color: #e6e6e6;"
            "  border: 0; border-radius: 4px; padding: 4px 12px;"
            "}"
            "QPushButton:hover { background: #3d6ea8; }"
        )
        resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.session))
        actions.addWidget(resume_btn)
        outer.addLayout(actions)

        self.setToolTip(f"ID: {session.id}\nOrigem: {session.origin_cwd}")

    def _title_text(self) -> str:
        if self.session.preview:
            text = self.session.preview.replace("\n", " ").strip()
            if len(text) > 60:
                return text[:59] + "…"
            return text
        return "(sem prompt registrado)"

    def _preview_text(self) -> str:
        return ""  # já tá no título; espaço pra extensão futura

    def _when_text(self) -> str:
        when = datetime.fromtimestamp(self.session.mtime)
        now = datetime.now()
        delta = now - when
        if when.date() == now.date():
            mins = int(delta.total_seconds() // 60)
            if mins < 1:
                return "agora"
            if mins < 60:
                return f"{mins}min"
            return when.strftime("%H:%M")
        if (now.date() - when.date()).days == 1:
            return "ontem"
        if (now.date() - when.date()).days < 7:
            return when.strftime("%a %H:%M")
        return when.strftime("%d/%m")
