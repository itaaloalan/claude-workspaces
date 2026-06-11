"""NotificationService — fachada com sinais Qt sobre o Store.

Responsabilidades:

- Receber chamadas `notify(...)` de emissores (terminals, plugins, hooks).
- Aplicar políticas: cooldown anti-spam, mute por tipo/workspace, dedup
  (atualiza entrada existente em vez de empilhar).
- Persistir em disco (delegando pra `persistence.py`).
- Emitir sinais Qt pra UI (sino, NotificationCenter, badges).
- Decidir se vai relembrar pendências (timer); a entrega em si (desktop
  notification, tray, badge) é feita por listeners — `NotificationService`
  só anuncia o evento.

Sinais:
- `notification_added(Notification)` — toda vez que uma entrada é criada *ou
  atualizada por dedup*. Listeners filtram pelo `occurrences` se quiser
  diferenciar "novo" de "repetiu".
- `notification_changed(Notification)` — mark_seen, snooze, dismiss
- `notification_removed(notif_id: str)`
- `unread_count_changed(int)` — pra atualizar o badge do sino
- `reminder_due(Notification)` — relembrete duma pendência (timer)
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from . import persistence
from .store import NotificationStore
from .types import Notification, NotificationKind, NotificationPriority

log = logging.getLogger(__name__)


class NotificationService(QObject):
    notification_added = Signal(object)  # Notification
    notification_changed = Signal(object)  # Notification
    notification_removed = Signal(str)  # notif_id
    unread_count_changed = Signal(int)
    reminder_due = Signal(object)  # Notification
    preferences_changed = Signal(dict)

    def __init__(
        self,
        path: Path | None = None,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._path = path
        items, prefs = ([], persistence.default_preferences())
        if path is not None:
            items, prefs = persistence.load(path)
        self._preferences: dict[str, Any] = prefs
        self._store = NotificationStore(history_limit=int(prefs.get("history_limit", 500)))
        self._store.restore(items)
        self._last_unread = self._store.unread_count()

        # Timer de relembrete para pendências actionable.
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setSingleShot(False)
        self._reminder_timer.timeout.connect(self._tick_reminders)
        self._apply_reminder_timer()
        # Última vez que cada entrada foi relembrada (in-memory; não persiste —
        # se o app reinicia, melhor relembrar de novo).
        self._last_reminder: dict[str, float] = {}
        # Silencer injetável: callable(workspace_id) -> True pra suprimir
        # notificações do workspace (ex.: minimizado). Avaliado a cada
        # notify/reminder — estado dinâmico, não preferência persistida.
        self._workspace_silencer: Callable[[str], bool] | None = None

    def set_workspace_silencer(self, fn: Callable[[str], bool] | None) -> None:
        """Callable(workspace_id) -> True pra suprimir notificações do
        workspace (ex.: minimizado). Avaliado a cada notify/reminder."""
        self._workspace_silencer = fn

    def _workspace_is_silenced(self, workspace_id: str | None) -> bool:
        if not workspace_id or self._workspace_silencer is None:
            return False
        try:
            return bool(self._workspace_silencer(workspace_id))
        except Exception:
            log.debug("workspace_silencer falhou", exc_info=True)
            return False

    # ---------------------------------------------------------- preferences

    @property
    def preferences(self) -> dict[str, Any]:
        return dict(self._preferences)

    def set_preferences(self, **changes: Any) -> None:
        before = dict(self._preferences)
        for k, v in changes.items():
            if k in self._preferences:
                self._preferences[k] = v
        if before == self._preferences:
            return
        if "history_limit" in changes:
            self._store.set_history_limit(int(self._preferences["history_limit"]))
        if "reminder_enabled" in changes or "reminder_seconds" in changes:
            self._apply_reminder_timer()
        self._flush()
        self.preferences_changed.emit(self.preferences)

    def _apply_reminder_timer(self) -> None:
        enabled = bool(self._preferences.get("reminder_enabled", True))
        secs = max(15, int(self._preferences.get("reminder_seconds", 120)))
        if not enabled:
            self._reminder_timer.stop()
            return
        self._reminder_timer.start(secs * 1000)

    # -------------------------------------------------------------- emitter

    def notify(
        self,
        kind: str,
        title: str,
        body: str = "",
        *,
        priority: str | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        tab_id: int | None = None,
        dedup_key: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Notification | None:
        """Emite uma notificação. Retorna a entrada criada/atualizada ou None
        se foi silenciada por preferência/cooldown."""
        # Mute por tipo
        if kind in (self._preferences.get("muted_kinds") or []):
            log.debug("notif silenciada (tipo %s mutado)", kind)
            return None
        # Mute por workspace
        if workspace_id and workspace_id in (self._preferences.get("muted_workspaces") or []):
            log.debug("notif silenciada (workspace %s mutado)", workspace_id)
            return None
        # Silencer dinâmico (workspace minimizado): nem cria a entrada —
        # nada de popup, discord, tray ou sino.
        if self._workspace_is_silenced(workspace_id):
            log.debug("notif silenciada (workspace %s minimizado)", workspace_id)
            return None

        candidate = Notification.make(
            kind=kind,
            title=title,
            body=body,
            priority=priority,
            workspace_id=workspace_id,
            session_id=session_id,
            tab_id=tab_id,
            dedup_key=dedup_key,
            data=data,
        )

        existing = self._store.find_by_dedup_key(candidate.dedup_key or "")
        now = time.time()
        cooldown = max(0, int(self._preferences.get("cooldown_seconds", 60)))

        if existing is not None:
            # Cooldown: se passou tempo curto e nada mudou, atualiza
            # silenciosamente — incrementa occurrences mas não emite evento
            # "novo" pra UI (evita re-toque/re-popup). Listeners que querem
            # ver atualizações se inscrevem em `notification_changed`.
            within_cooldown = (now - existing.updated_at) < cooldown
            self._store.update(
                existing.id,
                kind=candidate.kind,
                title=candidate.title,
                body=candidate.body,
                priority=candidate.priority,
                tab_id=candidate.tab_id if candidate.tab_id is not None else existing.tab_id,
                data={**existing.data, **candidate.data},
                occurrences=existing.occurrences + 1,
                seen=False if not within_cooldown else existing.seen,
                snoozed_until=existing.snoozed_until if within_cooldown else 0.0,
            )
            updated = self._store.get(existing.id)
            if updated is None:
                return None
            if within_cooldown:
                self.notification_changed.emit(updated)
            else:
                self.notification_added.emit(updated)
            self._announce_unread()
            self._flush()
            return updated

        added = self._store.add(candidate)
        self.notification_added.emit(added)
        self._announce_unread()
        self._flush()
        return added

    # -------------------------------------------------------------- mutators

    def mark_seen(self, notif_id: str) -> None:
        n = self._store.mark_seen(notif_id)
        if n is not None:
            self.notification_changed.emit(n)
            self._announce_unread()
            self._flush()

    def mark_all_seen(self) -> None:
        changed = self._store.mark_all_seen()
        if changed:
            for n in self._store.snapshot():
                self.notification_changed.emit(n)
            self._announce_unread()
            self._flush()

    def snooze(self, notif_id: str, seconds: int) -> None:
        n = self._store.snooze(notif_id, seconds)
        if n is not None:
            self._last_reminder[notif_id] = time.time()
            self.notification_changed.emit(n)
            self._flush()

    def dismiss(self, notif_id: str) -> None:
        n = self._store.dismiss(notif_id)
        if n is not None:
            self.notification_changed.emit(n)
            self._announce_unread()
            self._flush()

    def remove(self, notif_id: str) -> None:
        if self._store.remove(notif_id):
            self._last_reminder.pop(notif_id, None)
            self.notification_removed.emit(notif_id)
            self._announce_unread()
            self._flush()

    def clear_dismissed(self) -> int:
        removed = self._store.clear_dismissed()
        if removed:
            self._announce_unread()
            self._flush()
        return removed

    def clear_all(self) -> int:
        removed = self._store.clear_all()
        if removed:
            self._announce_unread()
            self._flush()
        return removed

    # ------------------------------------------------------------- accessors

    def list(self, **kwargs: Any) -> list[Notification]:
        return self._store.list(**kwargs)

    def get(self, notif_id: str) -> Notification | None:
        return self._store.get(notif_id)

    def find_by_dedup_key(self, key: str) -> Notification | None:
        return self._store.find_by_dedup_key(key)

    def unread_count(self, *, workspace_id: str | None = None) -> int:
        return self._store.unread_count(workspace_id=workspace_id)

    def unread_by_workspace(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._store.snapshot():
            if n.dismissed or n.seen or not n.workspace_id:
                continue
            counts[n.workspace_id] = counts.get(n.workspace_id, 0) + 1
        return counts

    def unread_by_session(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._store.snapshot():
            if n.dismissed or n.seen or not n.session_id:
                continue
            counts[n.session_id] = counts.get(n.session_id, 0) + 1
        return counts

    # ------------------------------------------------------------ reminders

    def _tick_reminders(self) -> None:
        secs = max(15, int(self._preferences.get("reminder_seconds", 120)))
        now = time.time()
        # _last_reminder acumula um key por notif que já lembrou — poda os
        # que não existem mais no store (removidos por history_limit,
        # clear_all, etc.) pra não crescer pela vida inteira da sessão.
        if len(self._last_reminder) > 64:
            alive = {n.id for n in self._store.snapshot()}
            for nid in [k for k in self._last_reminder if k not in alive]:
                self._last_reminder.pop(nid, None)
        for n in self._store.actionable_pending():
            # Workspace silenciado (minimizado) não recebe nem reminders de
            # pendências criadas antes de minimizar.
            if n.seen or self._workspace_is_silenced(n.workspace_id):
                continue
            last = self._last_reminder.get(n.id, n.created_at)
            if (now - last) >= secs:
                self._last_reminder[n.id] = now
                self.reminder_due.emit(n)

    # ----------------------------------------------------------- persistence

    def _flush(self) -> None:
        if self._path is None:
            return
        persistence.save(self._path, self._store.snapshot(), self._preferences)

    def _announce_unread(self) -> None:
        count = self._store.unread_count()
        if count != self._last_unread:
            self._last_unread = count
            self.unread_count_changed.emit(count)


__all__ = [
    "NotificationKind",
    "NotificationPriority",
    "NotificationService",
]
