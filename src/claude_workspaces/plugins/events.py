"""Catálogo de eventos (seção 7 da spec) + event bus de plugins.

O bus é simples: in-process, fan-out, isolado por plugin. Cada subscription
roda dentro de um try/except (handler que crasha **não** derruba os demais).

Throttle/debounce funcionam por subscription (1 hook = 1 throttler)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# Catálogo da seção 7 — qualquer evento fora daqui é rejeitado na validação.
EVENT_CATALOG: dict[str, set[str]] = {
    "session.created": {"sessionId", "workspaceId", "createdAt"},
    "session.status-changed": {"sessionId", "oldStatus", "newStatus", "durationMs"},
    "session.message-sent": {"sessionId", "messageId", "length"},
    "session.completed": {"sessionId", "reason", "durationMs"},
    "workspace.opened": {"workspaceId"},
    "workspace.closed": {"workspaceId"},
    "commit.created": {"workspaceId", "sha", "message"},
    "plugin.config-changed": {"key", "oldValue", "newValue"},
}

# Eventos de alta frequência exigem throttle ou debounce no manifesto (seção 7).
HIGH_FREQUENCY_EVENTS: frozenset[str] = frozenset({"session.message-sent"})

# Status válidos para session.status-changed
SESSION_STATUSES: frozenset[str] = frozenset(
    {"running", "awaiting-input", "idle", "completed", "error"}
)


def is_known_event(event: str) -> bool:
    return event in EVENT_CATALOG


def is_high_frequency(event: str) -> bool:
    return event in HIGH_FREQUENCY_EVENTS


# ----------------------------- Bus ----------------------------------------

Handler = Callable[[dict[str, Any]], None]


@dataclass
class _Subscription:
    plugin_id: str
    event: str
    handler: Handler
    throttle_ms: int = 0
    debounce_ms: int = 0
    # estado interno
    _last_fired_at: float = 0.0
    _debounce_timer: threading.Timer | None = field(default=None, repr=False)

    def _fire(self, payload: dict[str, Any]) -> None:
        try:
            self.handler(payload)
        except Exception:  # noqa: BLE001 — handlers que crashan não derrubam o bus
            log.exception(
                "[%s] handler do evento %s falhou (bus continua, demais "
                "subscribers não são afetados) | payload=%s",
                self.plugin_id,
                self.event,
                payload,
            )

    def dispatch(self, payload: dict[str, Any]) -> None:
        now = time.monotonic() * 1000
        if self.throttle_ms > 0:
            if now - self._last_fired_at < self.throttle_ms:
                return
            self._last_fired_at = now
            self._fire(payload)
            return
        if self.debounce_ms > 0:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            t = threading.Timer(self.debounce_ms / 1000.0, self._fire, args=(payload,))
            t.daemon = True
            self._debounce_timer = t
            t.start()
            return
        self._fire(payload)


class EventBus:
    """Bus in-process para eventos de plugins.

    Thread-safe: publish e subscribe podem ser chamados de qualquer thread."""

    def __init__(self) -> None:
        self._subs: dict[str, list[_Subscription]] = {}
        self._lock = threading.RLock()

    def subscribe(
        self,
        plugin_id: str,
        event: str,
        handler: Handler,
        throttle_ms: int = 0,
        debounce_ms: int = 0,
    ) -> _Subscription:
        if throttle_ms and debounce_ms:
            raise ValueError("throttle_ms e debounce_ms são mutuamente exclusivos")
        sub = _Subscription(plugin_id, event, handler, throttle_ms, debounce_ms)
        with self._lock:
            self._subs.setdefault(event, []).append(sub)
        return sub

    def unsubscribe(self, sub: _Subscription) -> None:
        with self._lock:
            lst = self._subs.get(sub.event)
            if not lst:
                return
            try:
                lst.remove(sub)
            except ValueError:
                pass

    def unsubscribe_plugin(self, plugin_id: str) -> int:
        """Remove todas as subscriptions de um plugin (usado no uninstall)."""
        removed = 0
        with self._lock:
            for event, lst in self._subs.items():  # noqa: B007 — event é usado pelo log
                keep = [s for s in lst if s.plugin_id != plugin_id]
                removed += len(lst) - len(keep)
                self._subs[event] = keep
        return removed

    def publish(self, event: str, payload: dict[str, Any]) -> int:
        """Publica `event` com `payload` e retorna nº de subscribers despachados."""
        if not is_known_event(event):
            # Não fail-hard: o host pode publicar eventos extras no futuro.
            # Mas avisa no log pra catch typos.
            log.warning("publish: evento desconhecido %r — typo?", event)
        with self._lock:
            subs = list(self._subs.get(event, ()))
        if subs:
            log.debug(
                "publish %s → %d subscriber(s): %s | payload=%s",
                event,
                len(subs),
                ",".join(sorted({s.plugin_id for s in subs})),
                payload,
            )
        else:
            log.debug("publish %s → 0 subscribers (ninguém escutando)", event)
        for sub in subs:
            sub.dispatch(payload)
        return len(subs)

    def subscriber_count(self, event: str | None = None) -> int:
        with self._lock:
            if event is None:
                return sum(len(lst) for lst in self._subs.values())
            return len(self._subs.get(event, ()))
