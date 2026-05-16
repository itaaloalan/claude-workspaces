"""Testes dos handlers do Focus Timer."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commands.reset_today import handler as reset_handler  # noqa: E402
from commands.show_today import _fmt_duration  # noqa: E402
from commands.show_today import handler as show_handler  # noqa: E402
from hooks.on_completed import handler as on_completed  # noqa: E402
from hooks.on_status import handler as on_status  # noqa: E402

from claude_workspaces.plugin_api import (  # noqa: E402
    SessionCompletedPayload,
    SessionStatusChangedPayload,
)


def _make_ctx(*, count_idle: bool = False, initial: dict | None = None):
    store: dict = dict(initial or {})
    notifies: list[dict] = []
    toasts: list[dict] = []

    async def get_config(key: str):
        return {"count_idle_as_focus": count_idle}[key]

    async def s_get(key: str):
        return store.get(key)

    async def s_set(key: str, value):
        store[key] = value

    async def s_delete(key: str):
        store.pop(key, None)

    async def s_clear():
        store.clear()

    async def notify(**kwargs):
        notifies.append(kwargs)

    async def toast(**kwargs):
        toasts.append(kwargs)

    return SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        storage=SimpleNamespace(get=s_get, set=s_set, delete=s_delete, clear=s_clear),
        ui=SimpleNamespace(notify=notify, toast=toast),
        log=SimpleNamespace(
            info=lambda *a, **k: None,
            warn=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
        _store=store,
        _notifies=notifies,
        _toasts=toasts,
    )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_on_status_acumula_running():
    ctx = _make_ctx()
    asyncio.run(
        on_status(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1",
                old_status="running",
                new_status="awaiting-input",
                duration_ms=120_000,
            ),
        )
    )
    assert ctx._store[f"day:{_today()}:running_ms"] == 120_000


def test_on_status_soma_acumulado_existente():
    key = f"day:{_today()}:running_ms"
    ctx = _make_ctx(initial={key: 60_000})
    asyncio.run(
        on_status(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1",
                old_status="running",
                new_status="idle",
                duration_ms=30_000,
            ),
        )
    )
    assert ctx._store[key] == 90_000


def test_on_status_ignora_idle_por_padrao():
    ctx = _make_ctx(count_idle=False)
    asyncio.run(
        on_status(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1",
                old_status="idle",
                new_status="running",
                duration_ms=500_000,
            ),
        )
    )
    assert ctx._store == {}


def test_on_status_conta_idle_quando_habilitado():
    ctx = _make_ctx(count_idle=True)
    asyncio.run(
        on_status(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1",
                old_status="idle",
                new_status="running",
                duration_ms=500_000,
            ),
        )
    )
    assert ctx._store[f"day:{_today()}:idle_ms"] == 500_000


def test_on_status_ignora_status_fora_da_lista():
    ctx = _make_ctx()
    asyncio.run(
        on_status(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1",
                old_status="completed",
                new_status="error",
                duration_ms=999,
            ),
        )
    )
    assert ctx._store == {}


def test_on_completed_incrementa_contadores():
    ctx = _make_ctx()
    asyncio.run(
        on_completed(
            ctx,
            SessionCompletedPayload(
                session_id="s1", reason="finished", duration_ms=200_000
            ),
        )
    )
    asyncio.run(
        on_completed(
            ctx,
            SessionCompletedPayload(
                session_id="s2", reason="finished", duration_ms=100_000
            ),
        )
    )
    assert ctx._store[f"day:{_today()}:completed_count"] == 2
    assert ctx._store[f"day:{_today()}:completed_total_ms"] == 300_000


def test_show_handler_monta_notificacao_com_totais():
    today = _today()
    ctx = _make_ctx(initial={
        f"day:{today}:running_ms": 3_600_000,
        f"day:{today}:awaiting-input_ms": 600_000,
        f"day:{today}:idle_ms": 0,
        f"day:{today}:completed_count": 3,
    })
    asyncio.run(show_handler(ctx))
    assert len(ctx._notifies) == 1
    body = ctx._notifies[0]["body"]
    assert "Running: 1h" in body
    assert "Aguardando: 10min" in body
    assert "concluídas: 3" in body


def test_reset_handler_limpa_chaves_do_dia():
    today = _today()
    ctx = _make_ctx(initial={
        f"day:{today}:running_ms": 100,
        f"day:{today}:completed_count": 1,
        "day:2020-01-01:running_ms": 42,  # outro dia: não deve sumir
    })
    asyncio.run(reset_handler(ctx))
    assert f"day:{today}:running_ms" not in ctx._store
    assert f"day:{today}:completed_count" not in ctx._store
    assert ctx._store["day:2020-01-01:running_ms"] == 42
    assert len(ctx._toasts) == 1


def test_fmt_duration():
    assert _fmt_duration(0) == "0min"
    assert _fmt_duration(60_000) == "1min"
    assert _fmt_duration(3_600_000) == "1h"
    assert _fmt_duration(3_660_000) == "1h01min"
