"""Testes do handler de idle-rescue."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hooks.on_status import handler  # noqa: E402

from claude_workspaces.plugin_api import SessionStatusChangedPayload  # noqa: E402


def _make_ctx(
    *,
    threshold: int = 10,
    style: str = "gentil",
    include_last: bool = True,
    last_message: str | None = "implementar parser",
):
    notifies: list[dict] = []
    logs: list[tuple[str, str, dict]] = []

    async def get_config(key: str):
        return {
            "idle_threshold_minutes": threshold,
            "nudge_style": style,
            "include_last_message": include_last,
        }[key]

    async def get_session(_id: str):
        return SimpleNamespace(
            id=_id,
            workspace_id="ws1",
            workspace_name="meu-projeto",
            status="awaiting-input",
            last_message=last_message,
        )

    async def notify(**kwargs):
        notifies.append(kwargs)

    def log_info(msg, **data):
        logs.append(("info", msg, data))

    return SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        sessions=SimpleNamespace(get=get_session),
        ui=SimpleNamespace(notify=notify),
        log=SimpleNamespace(info=log_info, warn=lambda *a, **k: None, error=lambda *a, **k: None),
        _notifies=notifies,
        _logs=logs,
    )


def _payload(duration_ms: int, new_status: str = "awaiting-input"):
    return SessionStatusChangedPayload(
        session_id="s1",
        old_status="running",
        new_status=new_status,
        duration_ms=duration_ms,
    )


def test_ignora_quando_status_nao_e_awaiting_input():
    ctx = _make_ctx()
    asyncio.run(handler(ctx, _payload(99 * 60 * 1000, new_status="completed")))
    assert ctx._notifies == []


def test_nao_notifica_abaixo_do_threshold():
    ctx = _make_ctx(threshold=10)
    asyncio.run(handler(ctx, _payload(5 * 60 * 1000)))
    assert ctx._notifies == []


def test_notifica_acima_do_threshold_com_estilo_gentil():
    ctx = _make_ctx(threshold=5, style="gentil")
    asyncio.run(handler(ctx, _payload(10 * 60 * 1000)))
    assert len(ctx._notifies) == 1
    n = ctx._notifies[0]
    assert n["title"].startswith("Bora")
    assert "meu-projeto" in n["body"]
    assert "implementar parser" in n["body"]


def test_estilo_direto_muda_o_titulo():
    ctx = _make_ctx(threshold=1, style="direto")
    asyncio.run(handler(ctx, _payload(2 * 60 * 1000)))
    assert ctx._notifies[0]["title"] == "Sessão parada."


def test_include_last_off_omite_a_ultima_mensagem():
    ctx = _make_ctx(threshold=1, include_last=False)
    asyncio.run(handler(ctx, _payload(2 * 60 * 1000)))
    body = ctx._notifies[0]["body"]
    assert "Último:" not in body


def test_truncamento_da_ultima_mensagem():
    longa = "x" * 200
    ctx = _make_ctx(threshold=1, last_message=longa)
    asyncio.run(handler(ctx, _payload(2 * 60 * 1000)))
    body = ctx._notifies[0]["body"]
    assert "…" in body
