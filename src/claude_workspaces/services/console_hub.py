"""ConsoleHub — tee do PTY dos consoles pro espelho no browser.

O console do browser (extensão) é um SEGUNDO view do MESMO PtySession do
console embutido: o output é publicado aqui (além do bridge Qt) e o
input do browser entra no mesmo fd — sincronizado por construção.

Thread model: `attach`/`publish` rodam na UI thread (signals Qt);
`subscribe`/`unsubscribe`/`write`/`replay` rodam nas threads dos handlers
HTTP. Tudo protegido por um lock; `PtySession.write` é `os.write` no fd
do PTY — seguro de outra thread pra chunks pequenos.
"""

from __future__ import annotations

import logging
import queue
import threading
import weakref

log = logging.getLogger(__name__)

_RING_MAX = 200_000  # bytes de backlog por sessão (replay inicial)
_QUEUE_MAX = 500     # chunks pendentes por subscriber (browser lento)


class ConsoleHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # sid → ring buffer (bytes) do output já visto.
        self._rings: dict[str, bytes] = {}
        # sid → lista de Queues de subscribers (SSE).
        self._subs: dict[str, list[queue.Queue]] = {}
        # sid → weakref do TerminalWidget (pro input).
        self._terms: dict[str, weakref.ref] = {}

    # ---- lado UI (Qt) -------------------------------------------------------

    def attach(self, key: str, term) -> None:
        """Registra o terminal dono do sid (input do browser usa
        term.session.write). Re-attach com o mesmo key é idempotente."""
        with self._lock:
            self._terms[key] = weakref.ref(term)

    def rekey(self, old: str, new: str) -> None:
        """Sid resolvido tarde (pending → real): migra ring/subs/term."""
        if old == new:
            return
        with self._lock:
            if old in self._rings:
                self._rings[new] = self._rings.pop(old)
            if old in self._subs:
                self._subs.setdefault(new, []).extend(self._subs.pop(old))
            if old in self._terms:
                self._terms[new] = self._terms.pop(old)

    def publish(self, key: str, data: bytes) -> None:
        """Output do PTY (tee) — alimenta o ring e os subscribers."""
        if not data:
            return
        with self._lock:
            ring = self._rings.get(key, b"") + data
            self._rings[key] = ring[-_RING_MAX:]
            subs = list(self._subs.get(key, []))
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                # Browser não está drenando — descarta o chunk (o xterm
                # de lá perde um pedaço; melhor que travar a UI).
                pass

    # ---- lado HTTP ------------------------------------------------------------

    def replay(self, sid: str) -> bytes:
        with self._lock:
            return self._rings.get(sid, b"")

    def subscribe(self, sid: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        with self._lock:
            self._subs.setdefault(sid, []).append(q)
        return q

    def unsubscribe(self, sid: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subs.get(sid, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subs.pop(sid, None)

    def write(self, sid: str, data: bytes) -> bool:
        """Input do browser → mesmo PTY do console do app."""
        with self._lock:
            ref = self._terms.get(sid)
        term = ref() if ref is not None else None
        if term is None:
            return False
        try:
            term.session.write(data)
            return True
        except Exception:
            log.warning("write no PTY de %s falhou", sid, exc_info=True)
            return False

    def has_session(self, sid: str) -> bool:
        with self._lock:
            ref = self._terms.get(sid)
        return ref is not None and ref() is not None
