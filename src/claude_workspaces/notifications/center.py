"""NotificationCenter — popup com filtros, cards e ações rápidas.

Substitui o `QMenu` espartano do `MainWindow._show_inbox`. É frameless,
ancorado debaixo da bell, fecha quando perde foco.

Layout:

    ┌──────────────────────────────────────────────┐
    │ Notificações                       [✓ tudo]  │
    │ [Todas] [Pendências] [Hoje] [Workspace ▾]    │
    ├──────────────────────────────────────────────┤
    │ ⚠  Permissão necessária — ws-foo         5s  │
    │    `git push origin main`                    │
    │    [Abrir] [Adiar 5m] [Já vi] [Descartar]    │
    ├──────────────────────────────────────────────┤
    │ ✓  Tarefa concluída — ws-bar             2m  │
    │    Suite passou (589 testes)                 │
    │    [Abrir]                          [✕]      │
    └──────────────────────────────────────────────┘

Sem entradas: ilustração + texto "Tá tudo em dia".
"""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .service import NotificationService
from .types import (
    ACTIONABLE_KINDS,
    Notification,
    NotificationKind,
    NotificationPriority,
)

# Mapa kind → (ícone-qtawesome, cor da borda lateral do card).
_KIND_VISUAL: dict[str, tuple[str, str]] = {
    NotificationKind.PERMISSION_REQUIRED: ("fa5s.shield-alt", "#e0892f"),
    NotificationKind.AGENT_WAITING: ("fa5s.hourglass-half", "#c9772d"),
    NotificationKind.TASK_COMPLETED: ("fa5s.check-circle", "#5ac35a"),
    NotificationKind.TASK_FAILED: ("fa5s.exclamation-triangle", "#d6504c"),
    NotificationKind.AGENT_IDLE: ("fa5s.coffee", "#9aa0a6"),
    NotificationKind.LONG_RUNNING: ("fa5s.clock", "#6aa9e0"),
    NotificationKind.COST_WARNING: ("fa5s.dollar-sign", "#e0892f"),
    NotificationKind.WORKSPACE_ERROR: ("fa5s.bug", "#d6504c"),
}

_KIND_LABEL: dict[str, str] = {
    NotificationKind.PERMISSION_REQUIRED: "Permissão",
    NotificationKind.AGENT_WAITING: "Aguardando",
    NotificationKind.TASK_COMPLETED: "Concluído",
    NotificationKind.TASK_FAILED: "Falhou",
    NotificationKind.AGENT_IDLE: "Ocioso",
    NotificationKind.LONG_RUNNING: "Demorado",
    NotificationKind.COST_WARNING: "Custo",
    NotificationKind.WORKSPACE_ERROR: "Erro",
}


def _humanize_age(epoch: float, *, now: float | None = None) -> str:
    n = now if now is not None else time.time()
    delta = max(0, int(n - epoch))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


class NotificationCard(QFrame):
    """Card individual. Emite sinais pra ações; o Center conecta neles."""

    open_clicked = Signal(str)  # notif_id
    snooze_clicked = Signal(str, int)  # notif_id, seconds
    dismiss_clicked = Signal(str)
    seen_clicked = Signal(str)

    def __init__(self, notification: Notification, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._n = notification
        self.setObjectName("NotificationCard")
        icon_name, accent = _KIND_VISUAL.get(
            notification.kind, ("fa5s.info-circle", "#6aa9e0")
        )
        self.setStyleSheet(
            "QFrame#NotificationCard {"
            "  background: #1c1c1c; border: 1px solid #2a2a2a; border-radius: 8px;"
            f"  border-left: 3px solid {accent};"
            "}"
            "QFrame#NotificationCard[unseen=\"true\"] {"
            "  background: #20242c;"
            "}"
            "QLabel { background: transparent; }"
        )
        self.setProperty("unseen", "true" if not notification.seen else "false")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        # ---------- header: ícone + tipo + workspace + idade
        header = QHBoxLayout()
        header.setSpacing(6)
        from ..ui.icons import ic as _ic
        ico = QLabel()
        ico.setPixmap(_ic(icon_name, color=accent).pixmap(QSize(13, 13)))
        header.addWidget(ico)
        kind_lbl = QLabel(_KIND_LABEL.get(notification.kind, notification.kind))
        kind_lbl.setStyleSheet(f"color: {accent}; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;")
        header.addWidget(kind_lbl)
        if notification.priority == NotificationPriority.CRITICAL:
            crit = QLabel("CRÍTICA")
            crit.setStyleSheet("color: #fff; background: #d6504c; font-size: 9px; font-weight: 700; border-radius: 3px; padding: 1px 5px;")
            header.addWidget(crit)
        if notification.occurrences > 1:
            occ = QLabel(f"×{notification.occurrences}")
            occ.setStyleSheet("color: #888; font-size: 10px;")
            header.addWidget(occ)
        header.addStretch()
        age = QLabel(_humanize_age(notification.updated_at))
        age.setStyleSheet("color: #707070; font-size: 10px;")
        header.addWidget(age)
        outer.addLayout(header)

        # ---------- título + body
        title_lbl = QLabel(notification.title)
        title_lbl.setStyleSheet("color: #e6e6e6; font-size: 12px; font-weight: 600;")
        title_lbl.setWordWrap(True)
        outer.addWidget(title_lbl)
        if notification.body:
            body_lbl = QLabel(notification.body)
            body_lbl.setStyleSheet("color: #b8b8b8; font-size: 11px;")
            body_lbl.setWordWrap(True)
            outer.addWidget(body_lbl)
        if notification.is_snoozed():
            sn = QLabel(f"⏱ adiada — volta em {_humanize_age(time.time(), now=notification.snoozed_until)}")
            sn.setStyleSheet("color: #c9772d; font-size: 10px; font-style: italic;")
            outer.addWidget(sn)

        # ---------- ações
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.setContentsMargins(0, 2, 0, 0)
        if notification.workspace_id or notification.tab_id is not None:
            open_btn = self._mk_btn("Abrir", primary=True)
            open_btn.clicked.connect(lambda: self.open_clicked.emit(self._n.id))
            actions.addWidget(open_btn)
        if notification.is_actionable() and not notification.is_snoozed():
            sn_btn = self._mk_btn("Adiar 5m")
            sn_btn.clicked.connect(lambda: self.snooze_clicked.emit(self._n.id, 5 * 60))
            actions.addWidget(sn_btn)
        if not notification.seen:
            seen_btn = self._mk_btn("Já vi")
            seen_btn.clicked.connect(lambda: self.seen_clicked.emit(self._n.id))
            actions.addWidget(seen_btn)
        actions.addStretch()
        dis_btn = self._mk_btn("✕", flat=True)
        dis_btn.setToolTip("Descartar")
        dis_btn.clicked.connect(lambda: self.dismiss_clicked.emit(self._n.id))
        actions.addWidget(dis_btn)
        outer.addLayout(actions)

    @staticmethod
    def _mk_btn(label: str, *, primary: bool = False, flat: bool = False) -> QPushButton:
        b = QPushButton(label)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if primary:
            b.setStyleSheet(
                "QPushButton { background: #3d6ea8; color: #fff; border: 0; "
                "border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 600; }"
                "QPushButton:hover { background: #4a82c5; }"
            )
        elif flat:
            b.setStyleSheet(
                "QPushButton { background: transparent; color: #888; border: 0; "
                "padding: 4px 6px; font-size: 13px; }"
                "QPushButton:hover { color: #d6504c; }"
            )
        else:
            b.setStyleSheet(
                "QPushButton { background: #1f1f1f; color: #c8c8c8; "
                "border: 1px solid #2c2c2c; border-radius: 4px; "
                "padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
            )
        return b


class NotificationCenter(QFrame):
    """Popup principal. Mostrado via `show_at(anchor)` debaixo da bell."""

    open_target_requested = Signal(object)  # Notification

    FILTERS = ("all", "pending", "today")

    def __init__(
        self,
        service: NotificationService,
        *,
        workspace_name_fn: Callable[[str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._service = service
        self._workspace_name_fn = workspace_name_fn or (lambda wid: wid)
        self._current_filter = "pending"
        self._current_workspace: str | None = None
        self.setObjectName("NotificationCenter")
        self.setStyleSheet(
            "QFrame#NotificationCenter {"
            "  background: #161616; border: 1px solid #2c2c2c; border-radius: 10px;"
            "}"
            "QLabel { background: transparent; }"
        )
        self.setFixedWidth(420)
        self.setMinimumHeight(180)
        self.setMaximumHeight(560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # --------------------------------------------------- header
        header = QHBoxLayout()
        title = QLabel("Notificações")
        title.setStyleSheet("color: #e6e6e6; font-size: 13px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        self._mark_all_btn = QPushButton("Marcar todas como vistas")
        self._mark_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._mark_all_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #6aa9e0; border: 0; "
            "font-size: 11px; padding: 2px 4px; }"
            "QPushButton:hover { color: #4a82c5; text-decoration: underline; }"
        )
        self._mark_all_btn.clicked.connect(self._service.mark_all_seen)
        header.addWidget(self._mark_all_btn)
        outer.addLayout(header)

        # --------------------------------------------------- filtros
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._filter_btns: dict[str, QPushButton] = {}
        for key, label in (("all", "Todas"), ("pending", "Pendências"), ("today", "Hoje")):
            b = QPushButton(label)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self._set_filter(k))
            filter_row.addWidget(b)
            self._filter_btns[key] = b
        filter_row.addStretch()
        self._clear_btn = QPushButton("Limpar histórico")
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: 0; "
            "font-size: 10px; padding: 2px 4px; }"
            "QPushButton:hover { color: #d6504c; text-decoration: underline; }"
        )
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        filter_row.addWidget(self._clear_btn)
        outer.addLayout(filter_row)

        # --------------------------------------------------- lista (scroll)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_holder = QWidget()
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_holder)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._scroll, stretch=1)

        # --------------------------------------------------- empty state
        self._empty = QLabel("Tá tudo em dia.\nNenhuma notificação pendente.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #707070; font-size: 12px; padding: 30px;")
        self._empty.hide()
        outer.addWidget(self._empty)

        # --------------------------------------------------- bindings
        service.notification_added.connect(self._refresh)
        service.notification_changed.connect(self._refresh)
        service.notification_removed.connect(self._refresh)

        self._set_filter("pending")

    # ------------------------------------------------------------ filtering

    def _set_filter(self, key: str) -> None:
        if key not in self.FILTERS:
            return
        self._current_filter = key
        for k, btn in self._filter_btns.items():
            checked = k == key
            btn.setChecked(checked)
            btn.setStyleSheet(
                "QPushButton { background: %s; color: %s; border: 1px solid #2c2c2c; "
                "border-radius: 4px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { border-color: #3d6ea8; }"
                % (
                    "#243044" if checked else "#1f1f1f",
                    "#6aa9e0" if checked else "#c8c8c8",
                )
            )
        self._refresh()

    def _filtered(self) -> list[Notification]:
        if self._current_filter == "pending":
            items = self._service.list(only_unseen=True)
        elif self._current_filter == "today":
            cutoff = time.time() - 86400
            items = [
                n for n in self._service.list()
                if n.updated_at >= cutoff
            ]
        else:
            items = self._service.list()
        if self._current_workspace:
            items = [n for n in items if n.workspace_id == self._current_workspace]
        return items

    # ----------------------------------------------------- list management

    def _refresh(self, *_args) -> None:
        # Limpa cards atuais (mantém o stretch no final).
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        items = self._filtered()
        if not items:
            self._scroll.hide()
            self._empty.show()
            return
        self._scroll.show()
        self._empty.hide()
        for n in items:
            # Anota workspace_name no body quando faz sentido.
            display = n
            if n.workspace_id:
                wsn = self._workspace_name_fn(n.workspace_id)
                if wsn and wsn != n.workspace_id and wsn not in n.title:
                    # cria cópia leve com título prefixado pelo workspace
                    display = Notification(
                        **{**n.__dict__, "title": f"{wsn} — {n.title}"}
                    )
            card = NotificationCard(display)
            card.open_clicked.connect(self._on_open)
            card.snooze_clicked.connect(self._service.snooze)
            card.dismiss_clicked.connect(self._service.dismiss)
            card.seen_clicked.connect(self._service.mark_seen)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _on_open(self, notif_id: str) -> None:
        n = self._service.get(notif_id)
        if n is None:
            return
        self._service.mark_seen(notif_id)
        self.open_target_requested.emit(n)
        self.hide()

    def _on_clear_clicked(self) -> None:
        # Limpa só os já vistos/descartados — pendentes ficam.
        self._service.clear_dismissed()
        # Tipos não actionable já lidos também viram histórico que dá pra
        # limpar; chamamos remove em cada um.
        for n in self._service.list():
            if n.seen and n.kind not in ACTIONABLE_KINDS:
                self._service.remove(n.id)

    # ------------------------------------------------------- show position

    def show_at(self, anchor_widget: QWidget) -> None:
        """Posiciona o popup logo abaixo do widget âncora, alinhado à direita."""
        self._refresh()
        gp = anchor_widget.mapToGlobal(anchor_widget.rect().bottomRight())
        x = gp.x() - self.width()
        y = gp.y() + 4
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()


__all__ = ["NotificationCard", "NotificationCenter"]
