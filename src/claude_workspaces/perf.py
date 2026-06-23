"""Instrumentação de performance leve e AGREGADA.

Em vez de logar evento a evento — o que viraria seu próprio gargalo num hot
path que dispara a cada 250ms ou a cada chunk de PTY —, acumula contadores e
tempos em memória e despeja um RESUMO periódico no `perf.log` (separado do
`app.log`). O objetivo é descobrir, com dados reais, onde o tempo/CPU vai num
app idle e sob carga, pra guiar otimizações futuras sem chutar.

Uso típico:

    from . import perf

    with perf.timed("git.status"):
        ...                            # mede a duração, soma no bucket

    perf.count("pty.bytes", len(data)) # contador puro (taxa por segundo)
    perf.count("poll.parsed")          # +1

    perf.flush()                       # escreve o resumo (chamado por timer)

Quando `perf.is_enabled()` é False (default até `init`), `timed`/`count` são
no-ops baratíssimos — nada é alocado e nada é gravado.

Thread-safety: `git.status` roda em threads do QThreadPool, então as
atualizações dos buckets são protegidas por um Lock. O custo do lock é
desprezível perto do que está sendo medido (subprocess, regex sobre KBs).
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

# Logger dedicado, configurado em `init()` pra escrever no perf.log com
# propagate=False (não polui app.log/stderr).
_log = logging.getLogger("perf")

_enabled: bool = False
_lock = threading.Lock()


@dataclass
class _Timer:
    n: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0


@dataclass
class _Counter:
    n: int = 0
    total: float = 0.0


# name -> bucket. Os nomes são controlados pelo código (conjunto pequeno e
# fixo), então os dicts não crescem sem limite.
_timers: dict[str, _Timer] = {}
_counters: dict[str, _Counter] = {}
# Início da janela de agregação atual (resetado a cada flush).
_window_start: float = time.monotonic()


def is_enabled() -> bool:
    return _enabled


def init(enabled: bool, log_path) -> None:
    """Liga/desliga a instrumentação e configura o handler do perf.log.

    Idempotente: chamada uma vez no startup (app.main) a partir do setting
    `perf_logging_enabled`. Quando desligado, instala nada e os helpers
    viram no-op.
    """
    global _enabled, _window_start
    _enabled = bool(enabled)
    if not _enabled:
        return
    from logging.handlers import RotatingFileHandler

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        _log.handlers.clear()
        _log.addHandler(handler)
        _log.setLevel(logging.INFO)
        # Não sobe pro root — perf.log é um silo separado.
        _log.propagate = False
    except Exception:
        # Falha ao montar o log de perf nunca pode derrubar o app.
        _enabled = False
        return
    _window_start = time.monotonic()
    _log.info("perf logging iniciado")


def record(name: str, dt_ms: float) -> None:
    """Soma uma duração (ms) ao bucket `name`. Use `timed()` quando puder."""
    if not _enabled:
        return
    with _lock:
        b = _timers.get(name)
        if b is None:
            b = _timers[name] = _Timer()
        b.n += 1
        b.total_ms += dt_ms
        if dt_ms > b.max_ms:
            b.max_ms = dt_ms


@contextmanager
def timed(name: str):
    """Mede o tempo de parede do bloco e soma no bucket `name`."""
    if not _enabled:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - t0) * 1000.0)


def count(name: str, amount: float = 1) -> None:
    """Incrementa um contador puro (ex.: bytes de PTY, nº de parses)."""
    if not _enabled:
        return
    with _lock:
        c = _counters.get(name)
        if c is None:
            c = _counters[name] = _Counter()
        c.n += 1
        c.total += amount


def flush() -> None:
    """Despeja o resumo da janela atual no perf.log e zera os buckets.

    Uma linha por métrica. Para timers: nº de chamadas, média/máx em ms,
    total acumulado na janela e quanto isso representa por segundo (o sinal
    mais direto de 'onde o CPU foi'). Para contadores: total e taxa/s.
    """
    if not _enabled:
        return
    now = time.monotonic()
    with _lock:
        window_s = max(1e-3, now - _window_start)
        timers = _timers.copy()
        counters = _counters.copy()
        _timers.clear()
        _counters.clear()
        _reset_window(now)
    if not timers and not counters:
        return
    lines = [f"=== janela {window_s:.1f}s ==="]
    for name in sorted(timers):
        b = timers[name]
        avg = b.total_ms / b.n if b.n else 0.0
        # ms gastos por segundo de janela = fração de 1 core (×1000 = 100%).
        ms_per_s = b.total_ms / window_s
        lines.append(
            f"  T {name:<28} n={b.n:<6} avg={avg:6.2f}ms "
            f"max={b.max_ms:7.2f}ms total={b.total_ms:8.1f}ms "
            f"({ms_per_s:6.1f}ms/s)"
        )
    for name in sorted(counters):
        c = counters[name]
        rate = c.total / window_s
        lines.append(
            f"  C {name:<28} n={c.n:<6} total={c.total:12.0f} "
            f"rate={rate:12.1f}/s"
        )
    _log.info("\n".join(lines))


def _reset_window(now: float) -> None:
    global _window_start
    _window_start = now
