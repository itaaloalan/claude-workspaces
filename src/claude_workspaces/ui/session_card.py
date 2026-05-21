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
from ..session_marks import is_starred, set_starred


class SessionCard(QFrame):
    """Card visual pra uma sessão do Claude. Substitui o item cru de QListWidget."""

    resume_requested = Signal(ClaudeSession)
    delete_requested = Signal(ClaudeSession)
    handoff_requested = Signal(ClaudeSession)
    export_requested = Signal(ClaudeSession)
    star_toggled = Signal(ClaudeSession, bool)

    _BTN_GHOST = (
        "QPushButton {"
        "  background: transparent; color: #c8c8c8;"
        "  border: 1px solid #3a3a3a; border-radius: 3px;"
        "  padding: 1px 6px; font-size: 11px;"
        "}"
        "QPushButton:hover { color: #6aa9e0; border-color: #3d6ea8; }"
    )

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
            "  border-radius: 6px;"
            "}"
            "QFrame#SessionCard:hover { border-color: #3d6ea8; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 5)
        outer.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(6)

        self._starred = is_starred(session.id)
        self._star_btn = QPushButton()
        self._star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._star_btn.setFixedWidth(22)
        self._star_btn.setFlat(True)
        self._star_btn.clicked.connect(self._on_toggle_star)
        self._refresh_star_visual()
        header.addWidget(self._star_btn)

        title = QLabel(self._title_text())
        title.setStyleSheet("font-weight: 600; color: #e6e6e6; font-size: 12px;")
        title.setWordWrap(True)
        header.addWidget(title, stretch=1)

        # Badge Ativa (verde) / Concluída (cinza) — heurística:
        # sessão modificada nos últimos 5 minutos é "Ativa".
        import time
        is_active = (time.time() - session.mtime) < 300  # 5min
        badge = QLabel("Ativa" if is_active else "Concluída")
        if is_active:
            badge.setStyleSheet(
                "QLabel { background: rgba(90, 195, 90, 38); color: #5ac35a; "
                "font-size: 9px; font-weight: 700; padding: 2px 8px; "
                "border-radius: 8px; }"
            )
        else:
            badge.setStyleSheet(
                "QLabel { background: #2a2a2a; color: #9aa0a6; "
                "font-size: 9px; font-weight: 700; padding: 2px 8px; "
                "border-radius: 8px; }"
            )
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        when = QLabel(self._when_text())
        when.setStyleSheet("color: #8a8a8a; font-size: 10px;")
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(when)

        outer.addLayout(header)

        if show_origin:
            origin = QLabel(Path(session.origin_cwd).name)
            origin.setStyleSheet("color: #6aa9e0; font-size: 10px;")
            outer.addWidget(origin)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        actions.addStretch()

        delete_btn = QPushButton("✕")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setToolTip("Excluir o arquivo desta sessão (.jsonl)")
        delete_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; color: #888;"
            "  border: 1px solid #3a3a3a; border-radius: 3px;"
            "  padding: 1px 6px; font-size: 11px;"
            "}"
            "QPushButton:hover { color: #e57373; border-color: #a23a3a; }"
        )
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.session))
        actions.addWidget(delete_btn)

        export_btn = QPushButton("📝")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setToolTip("Exportar conversa como markdown")
        export_btn.setStyleSheet(self._BTN_GHOST)
        export_btn.clicked.connect(lambda: self.export_requested.emit(self.session))
        actions.addWidget(export_btn)

        handoff_btn = QPushButton("→ Handoff")
        handoff_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        handoff_btn.setToolTip(
            "Abrir novo Claude com briefing dessa sessão como primeira mensagem"
        )
        handoff_btn.setStyleSheet(self._BTN_GHOST)
        handoff_btn.clicked.connect(lambda: self.handoff_requested.emit(self.session))
        actions.addWidget(handoff_btn)

        # Label "Retomar" pra sessão ativa (azul mais forte), "Reabrir"
        # pra concluída (azul mais discreto). Match com mockup.
        resume_btn = QPushButton("Retomar" if is_active else "Reabrir")
        resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_active:
            resume_btn.setStyleSheet(
                "QPushButton {"
                "  background: #3d6ea8; color: #fff; font-weight: 600;"
                "  border: 0; border-radius: 3px;"
                "  padding: 2px 12px; font-size: 11px;"
                "}"
                "QPushButton:hover { background: #4a82c5; }"
            )
        else:
            resume_btn.setStyleSheet(
                "QPushButton {"
                "  background: #2d4a6e; color: #e6e6e6;"
                "  border: 0; border-radius: 3px;"
                "  padding: 2px 10px; font-size: 11px;"
                "}"
                "QPushButton:hover { background: #3d6ea8; }"
            )
        resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.session))
        actions.addWidget(resume_btn)
        outer.addLayout(actions)

        self.setToolTip(f"ID: {session.id}\nOrigem: {session.origin_cwd}")

    def _refresh_star_visual(self) -> None:
        if self._starred:
            self._star_btn.setText("★")
            self._star_btn.setToolTip("Favoritada — clique pra desmarcar")
            self._star_btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #f0c040;"
                "  border: 0; font-size: 14px; padding: 0;"
                "}"
                "QPushButton:hover { color: #ffd860; }"
            )
        else:
            self._star_btn.setText("☆")
            self._star_btn.setToolTip("Favoritar essa sessão (acha ela depois com o filtro ★)")
            self._star_btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #6a6a6a;"
                "  border: 0; font-size: 14px; padding: 0;"
                "}"
                "QPushButton:hover { color: #f0c040; }"
            )

    def _on_toggle_star(self) -> None:
        self._starred = not self._starred
        set_starred(self.session.id, self._starred, self.session.origin_cwd)
        self._refresh_star_visual()
        self.star_toggled.emit(self.session, self._starred)

    def _title_text(self) -> str:
        if self.session.preview:
            text = self.session.preview.replace("\n", " ").strip()
            if len(text) > 70:
                return text[:69] + "…"
            return text
        return "(sem prompt registrado)"

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
