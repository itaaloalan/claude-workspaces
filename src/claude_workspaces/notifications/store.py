"""NotificationStore — estado em memória + persistência.

Lógica pura (sem Qt) pra ficar testável sem QApplication. O serviço com
sinais Qt mora em `service.py` e delega o estado pra cá.

Operações expostas:

- `add(notification)` — empilha (dedup tratado no `NotificationService`, não aqui)
- `update(id, **fields)` — patch parcial; atualiza `updated_at`
- `mark_seen(id)` / `mark_all_seen()`
- `snooze(id, seconds)`
- `dismiss(id)`
- `remove(id)` / `clear_dismissed()` / `clear_all()`
- `list(...)` — filtros: kind, workspace_id, only_unseen, include_dismissed
- `find_by_dedup_key(key)` — usado pelo serviço pra deduplicar/atualizar
- `unread_count()` — não-dismissed e não-seen

Persistência: chamador (`NotificationService`) decide quando dar flush;
o store só expõe `snapshot()` / `restore()`.
"""
from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from .types import Notification


class NotificationStore:
    def __init__(self, *, history_limit: int = 500) -> None:
        self._items: list[Notification] = []
        self._history_limit = max(10, int(history_limit))

    # ------------------------------------------------------------------ CRUD

    def add(self, notification: Notification) -> Notification:
        self._items.append(notification)
        self._trim()
        return notification

    def update(self, notif_id: str, **fields: Any) -> Notification | None:
        for i, n in enumerate(self._items):
            if n.id != notif_id:
                continue
            for k, v in fields.items():
                if hasattr(n, k):
                    setattr(n, k, v)
            n.updated_at = time.time()
            self._items[i] = n
            return n
        return None

    def remove(self, notif_id: str) -> bool:
        before = len(self._items)
        self._items = [n for n in self._items if n.id != notif_id]
        return len(self._items) < before

    def clear_dismissed(self) -> int:
        before = len(self._items)
        self._items = [n for n in self._items if not n.dismissed]
        return before - len(self._items)

    def clear_all(self) -> int:
        n = len(self._items)
        self._items = []
        return n

    # ----------------------------------------------------------------- state

    def mark_seen(self, notif_id: str) -> Notification | None:
        return self.update(notif_id, seen=True)

    def mark_all_seen(self) -> int:
        count = 0
        for n in self._items:
            if not n.seen:
                n.seen = True
                n.updated_at = time.time()
                count += 1
        return count

    def snooze(self, notif_id: str, seconds: int) -> Notification | None:
        return self.update(
            notif_id,
            snoozed_until=time.time() + max(0, int(seconds)),
            seen=False,
        )

    def dismiss(self, notif_id: str) -> Notification | None:
        return self.update(notif_id, dismissed=True, seen=True)

    # --------------------------------------------------------------- queries

    def get(self, notif_id: str) -> Notification | None:
        for n in self._items:
            if n.id == notif_id:
                return n
        return None

    def find_by_dedup_key(self, key: str) -> Notification | None:
        """Mais recente com essa dedup_key e não-dismissed. Usado pelo
        serviço pra atualizar em vez de empilhar."""
        latest: Notification | None = None
        for n in self._items:
            if n.dismissed or n.dedup_key != key:
                continue
            if latest is None or n.updated_at > latest.updated_at:
                latest = n
        return latest

    def list(
        self,
        *,
        kind: str | None = None,
        workspace_id: str | None = None,
        only_unseen: bool = False,
        only_actionable: bool = False,
        include_dismissed: bool = False,
    ) -> list[Notification]:
        out: list[Notification] = []
        for n in self._items:
            if not include_dismissed and n.dismissed:
                continue
            if kind is not None and n.kind != kind:
                continue
            if workspace_id is not None and n.workspace_id != workspace_id:
                continue
            if only_unseen and n.seen:
                continue
            if only_actionable and not n.is_actionable():
                continue
            out.append(n)
        # Mais recentes primeiro.
        out.sort(key=lambda n: n.updated_at, reverse=True)
        return out

    def unread_count(self, *, workspace_id: str | None = None) -> int:
        return sum(
            1 for n in self._items
            if not n.dismissed
            and not n.seen
            and (workspace_id is None or n.workspace_id == workspace_id)
        )

    def actionable_pending(self) -> list[Notification]:
        """Pendências que devem ser relembradas — actionable, não dismissed,
        não snoozed no momento."""
        now = time.time()
        return [
            n for n in self._items
            if n.is_actionable()
            and not n.dismissed
            and not n.is_snoozed(now=now)
        ]

    # ----------------------------------------------------------- snapshotting

    def snapshot(self) -> list[Notification]:
        return list(self._items)

    def restore(self, items: Iterable[Notification]) -> None:
        self._items = list(items)
        self._trim()

    def set_history_limit(self, limit: int) -> None:
        self._history_limit = max(10, int(limit))
        self._trim()

    def _trim(self) -> None:
        if len(self._items) <= self._history_limit:
            return
        # Mantém os mais recentes.
        self._items.sort(key=lambda n: n.updated_at)
        self._items = self._items[-self._history_limit :]


__all__ = ["NotificationStore"]
