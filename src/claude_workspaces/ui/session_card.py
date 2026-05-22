from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from ..claude_sessions import ClaudeSession
from ..session_marks import is_starred, set_starred
from . import theme

SessionState = Literal["working", "awaiting", "idle", "error", "done"]

_STATE_LABEL = {
    "working": "Trabalhando",
    "awaiting": "Aguardando",
    "idle": "Ocioso",
    "error": "Erro",
    "done": "Concluída",
}
_STATE_COLOR = {
    "working": theme.STATE_WORKING,
    "awaiting": theme.STATE_AWAITING,
    "idle": theme.STATE_IDLE,
    "error": theme.STATE_ERROR,
    "done": theme.STATE_DONE,
}


class SessionCard(QFrame):
    """Card visual pra uma sessão do Claude. Substitui o item cru de QListWidget."""

    resume_requested = Signal(ClaudeSession)
    delete_requested = Signal(ClaudeSession)
    handoff_requested = Signal(ClaudeSession)
    export_requested = Signal(ClaudeSession)
    star_toggled = Signal(ClaudeSession, bool)

    def __init__(
        self,
        session: ClaudeSession,
        show_origin: bool = False,
        state: SessionState | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("SessionCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # Heurística default: sessão modificada nos últimos 5 min = "working",
        # senão "done". Caller pode sobrescrever passando state explícito
        # (awaiting / error / idle).
        if state is None:
            state = "working" if (time.time() - session.mtime) < 300 else "done"
        self._state: SessionState = state
        accent = _STATE_COLOR[self._state]
        self.setStyleSheet(theme.left_accent_qss(accent, object_name="SessionCard"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        self._starred = is_starred(session.id)
        self._star_btn = QPushButton()
        self._star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._star_btn.setFixedWidth(20)
        self._star_btn.setFlat(True)
        self._star_btn.clicked.connect(self._on_toggle_star)
        self._refresh_star_visual()
        header.addWidget(self._star_btn)
        # Estrela some no idle; reaparece em hover ou quando já marcada.
        self._star_btn.setVisible(self._starred)

        title = QLabel(self._title_text())
        title.setStyleSheet(
            f"font-weight: 600; color: {theme.TEXT_PRIMARY}; font-size: 12px;"
        )
        title.setWordWrap(False)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        # Elide longo: cabe na largura disponível sem quebrar visualmente feio.
        title.setMinimumWidth(0)
        header.addWidget(title, stretch=1)

        badge = QLabel(_STATE_LABEL[self._state])
        badge.setStyleSheet(theme.state_badge_qss(accent))
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        when = QLabel(self._when_text())
        when.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(when)

        outer.addLayout(header)

        if show_origin:
            origin = QLabel(Path(session.origin_cwd).name)
            origin.setStyleSheet(f"color: {theme.TEXT_LINK}; font-size: 10px;")
            outer.addWidget(origin)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addStretch()

        # ⋯ agrupa ações secundárias (delete, export, handoff) — só visível
        # em hover. Reduz poluição mantendo o card limpo no idle.
        self._more_btn = QPushButton("⋯")
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setFixedSize(22, 22)
        self._more_btn.setToolTip("Mais ações")
        self._more_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_FAINT}; "
            f"border: 0; border-radius: {theme.RADIUS_SM}px; font-size: 14px; }}"
            f"QPushButton:hover {{ background: {theme.BG_PANEL}; "
            f"color: {theme.TEXT_LINK}; }}"
        )
        self._more_btn.clicked.connect(self._open_menu)
        self._more_btn.setVisible(False)
        actions.addWidget(self._more_btn)

        # Botão principal — "Retomar" pra working/awaiting, "Reabrir" pro resto.
        is_live = self._state in ("working", "awaiting")
        resume_btn = QPushButton("Retomar" if is_live else "Reabrir")
        resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if is_live:
            resume_btn.setStyleSheet(
                f"QPushButton {{ background: {theme.PRIMARY}; color: {theme.TEXT_BRIGHT}; "
                f"font-weight: 600; border: 0; border-radius: {theme.RADIUS_SM}px; "
                f"padding: 3px 12px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {theme.PRIMARY_HOVER}; }}"
            )
        else:
            resume_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED}; "
                f"border: 1px solid {theme.BORDER_INPUT}; "
                f"border-radius: {theme.RADIUS_SM}px; padding: 3px 10px; font-size: 11px; }}"
                f"QPushButton:hover {{ border-color: {theme.PRIMARY}; "
                f"color: {theme.TEXT_LINK}; }}"
            )
        resume_btn.clicked.connect(lambda: self.resume_requested.emit(self.session))
        actions.addWidget(resume_btn)
        outer.addLayout(actions)

        self.setToolTip(f"ID: {session.id}\nOrigem: {session.origin_cwd}")

    def _open_menu(self) -> None:
        menu = QMenu(self._more_btn)
        menu.setStyleSheet(
            f"QMenu {{ background: {theme.BG_SURFACE}; "
            f"color: {theme.TEXT_PRIMARY}; border: 1px solid {theme.BORDER_INPUT}; }}"
            f"QMenu::item {{ padding: 6px 14px; }}"
            f"QMenu::item:selected {{ background: {theme.PRIMARY}; "
            f"color: {theme.TEXT_BRIGHT}; }}"
        )
        menu.addAction("→  Handoff (novo Claude com briefing)").triggered.connect(
            lambda: self.handoff_requested.emit(self.session)
        )
        menu.addAction("📝  Exportar como markdown").triggered.connect(
            lambda: self.export_requested.emit(self.session)
        )
        menu.addSeparator()
        del_action = menu.addAction("✕  Excluir sessão (.jsonl)")
        del_action.triggered.connect(lambda: self.delete_requested.emit(self.session))
        menu.exec_(self._more_btn.mapToGlobal(self._more_btn.rect().bottomRight()))

    def event(self, e: QEvent) -> bool:  # type: ignore[override]
        if e.type() == QEvent.Type.HoverEnter:
            self._more_btn.setVisible(True)
            self._star_btn.setVisible(True)
        elif e.type() == QEvent.Type.HoverLeave:
            self._more_btn.setVisible(False)
            self._star_btn.setVisible(self._starred)
        return super().event(e)

    def _refresh_star_visual(self) -> None:
        if self._starred:
            self._star_btn.setText("★")
            self._star_btn.setToolTip("Favoritada — clique pra desmarcar")
            self._star_btn.setStyleSheet(
                "QPushButton {"
                "  background: transparent; color: #f0c040;"
                "  border: 0; font-size: 13px; padding: 0;"
                "}"
                "QPushButton:hover { color: #ffd860; }"
            )
        else:
            self._star_btn.setText("☆")
            self._star_btn.setToolTip(
                "Favoritar essa sessão (acha ela depois com o filtro ★)"
            )
            self._star_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {theme.TEXT_FAINT}; "
                "border: 0; font-size: 13px; padding: 0; }}"
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
            if len(text) > 56:
                return text[:55] + "…"
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
