"""Testes do handler de session.status-changed.

Roda no ambiente do autor (pytest), não no host. Por isso podemos importar
`../src/hooks/on_status.py` relativamente — o analyzer pula `tests/`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Permite importar o handler localmente
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hooks.on_status import handler  # noqa: E402

from claude_workspaces.plugin_api import SessionStatusChangedPayload  # noqa: E402


def _make_ctx(threshold_min: int = 5):
    """ctx duplicado pra teste — só os atributos que o handler usa."""

    notify_calls: list[dict] = []

    async def get_config(key: str):
        assert key == "threshold_minutes"
        return threshold_min

    async def get_session(_id: str):
        return SimpleNamespace(workspace_name="ws", last_message="msg")

    async def notify(**kwargs):
        notify_calls.append(kwargs)

    return SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        sessions=SimpleNamespace(get=get_session),
        ui=SimpleNamespace(notify=notify),
        _notify_calls=notify_calls,
    )


def test_ignora_status_diferente_de_awaiting_input():
    ctx = _make_ctx()
    asyncio.run(
        handler(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1", old_status="running", new_status="idle",
                duration_ms=9_999_999,
            ),
        )
    )
    assert ctx._notify_calls == []


def test_nao_notifica_antes_do_threshold():
    ctx = _make_ctx(threshold_min=5)
    asyncio.run(
        handler(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1", old_status="running", new_status="awaiting-input",
                duration_ms=60_000,  # 1 min < 5 min
            ),
        )
    )
    assert ctx._notify_calls == []


def test_notifica_quando_passa_do_threshold():
    ctx = _make_ctx(threshold_min=1)
    asyncio.run(
        handler(
            ctx,
            SessionStatusChangedPayload(
                session_id="s1", old_status="running", new_status="awaiting-input",
                duration_ms=90_000,  # 1.5 min > 1 min
            ),
        )
    )
    assert len(ctx._notify_calls) == 1
    assert "aguardando" in ctx._notify_calls[0]["title"].lower()
