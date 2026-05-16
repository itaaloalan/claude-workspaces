"""Testes dos handlers do workspace-snapshot."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hooks.on_closed import _fmt_duration  # noqa: E402
from hooks.on_closed import handler as on_closed  # noqa: E402
from hooks.on_commit_created import handler as on_commit  # noqa: E402
from hooks.on_opened import handler as on_opened  # noqa: E402
from hooks.on_session_created import handler as on_session  # noqa: E402

from claude_workspaces.plugin_api import (  # noqa: E402
    CommitCreatedPayload,
    SessionCreatedPayload,
    WorkspaceClosedPayload,
    WorkspaceOpenedPayload,
)


def _make_ctx(
    *,
    notify_on_close: bool = True,
    min_seconds: int = 30,
    workspace_name: str | None = "meu-projeto",
    initial: dict | None = None,
):
    store: dict = dict(initial or {})
    notifies: list[dict] = []

    async def get_config(key: str):
        return {
            "notify_on_close": notify_on_close,
            "min_duration_seconds": min_seconds,
        }[key]

    async def s_get(key: str):
        return store.get(key)

    async def s_set(key: str, value):
        store[key] = value

    async def s_delete(key: str):
        store.pop(key, None)

    async def workspaces_get(_id: str):
        if workspace_name is None:
            raise RuntimeError("removido")
        return SimpleNamespace(id=_id, name=workspace_name, folders=())

    async def notify(**kwargs):
        notifies.append(kwargs)

    return SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        storage=SimpleNamespace(get=s_get, set=s_set, delete=s_delete),
        workspaces=SimpleNamespace(get=workspaces_get),
        ui=SimpleNamespace(notify=notify),
        log=SimpleNamespace(
            info=lambda *a, **k: None,
            warn=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
        _store=store,
        _notifies=notifies,
    )


def test_on_opened_cria_snapshot_zerado():
    ctx = _make_ctx()
    asyncio.run(on_opened(ctx, WorkspaceOpenedPayload(workspace_id="ws1")))
    snap = ctx._store["ws:ws1:current"]
    assert snap["sessions_created"] == 0
    assert snap["commits_created"] == 0
    assert snap["opened_at_ms"] > 0


def test_on_session_incrementa_apenas_se_snapshot_existir():
    ctx = _make_ctx(initial={
        "ws:ws1:current": {"opened_at_ms": 1, "sessions_created": 2, "commits_created": 0}
    })
    asyncio.run(on_session(ctx, SessionCreatedPayload(
        session_id="s1", workspace_id="ws1", created_at="2026-05-16T10:00:00Z",
    )))
    assert ctx._store["ws:ws1:current"]["sessions_created"] == 3


def test_on_session_ignora_quando_workspace_nao_esta_aberto():
    ctx = _make_ctx()
    asyncio.run(on_session(ctx, SessionCreatedPayload(
        session_id="s1", workspace_id="ws-fantasma", created_at="2026-05-16T10:00:00Z",
    )))
    assert ctx._store == {}


def test_on_commit_incrementa_apenas_se_snapshot_existir():
    ctx = _make_ctx(initial={
        "ws:ws1:current": {"opened_at_ms": 1, "sessions_created": 0, "commits_created": 4}
    })
    asyncio.run(on_commit(ctx, CommitCreatedPayload(
        workspace_id="ws1", sha="abc", message="feat: x",
    )))
    assert ctx._store["ws:ws1:current"]["commits_created"] == 5


def test_on_closed_notifica_com_resumo():
    opened_at_ms = int(time.time() * 1000) - 5 * 60 * 1000  # 5 min atrás
    ctx = _make_ctx(min_seconds=30, initial={
        "ws:ws1:current": {
            "opened_at_ms": opened_at_ms,
            "sessions_created": 2,
            "commits_created": 1,
        }
    })
    asyncio.run(on_closed(ctx, WorkspaceClosedPayload(workspace_id="ws1")))
    assert "ws:ws1:current" not in ctx._store
    assert len(ctx._notifies) == 1
    n = ctx._notifies[0]
    assert "meu-projeto" in n["title"]
    assert "Sessões abertas: 2" in n["body"]
    assert "Commits: 1" in n["body"]


def test_on_closed_respeita_duracao_minima():
    opened_at_ms = int(time.time() * 1000) - 10 * 1000  # 10s atrás
    ctx = _make_ctx(min_seconds=30, initial={
        "ws:ws1:current": {
            "opened_at_ms": opened_at_ms,
            "sessions_created": 1,
            "commits_created": 0,
        }
    })
    asyncio.run(on_closed(ctx, WorkspaceClosedPayload(workspace_id="ws1")))
    assert ctx._notifies == []
    assert "ws:ws1:current" not in ctx._store  # foi limpado mesmo sem notificar


def test_on_closed_sem_snapshot_e_no_op():
    ctx = _make_ctx()
    asyncio.run(on_closed(ctx, WorkspaceClosedPayload(workspace_id="ws-fantasma")))
    assert ctx._notifies == []


def test_on_closed_fallback_quando_workspace_some():
    opened_at_ms = int(time.time() * 1000) - 60 * 1000
    ctx = _make_ctx(min_seconds=10, workspace_name=None, initial={
        "ws:ws9:current": {
            "opened_at_ms": opened_at_ms,
            "sessions_created": 0,
            "commits_created": 0,
        }
    })
    asyncio.run(on_closed(ctx, WorkspaceClosedPayload(workspace_id="ws9")))
    assert len(ctx._notifies) == 1
    assert "ws9" in ctx._notifies[0]["title"]
    assert "Sem sessões" in ctx._notifies[0]["body"]


def test_fmt_duration():
    assert _fmt_duration(0) == "0s"
    assert _fmt_duration(45) == "45s"
    assert _fmt_duration(60) == "1min"
    assert _fmt_duration(90) == "1min30s"
    assert _fmt_duration(3600) == "1h"
    assert _fmt_duration(3660) == "1h01min"


def test_notify_off_pula_notificacao():
    opened_at_ms = int(time.time() * 1000) - 60 * 1000
    ctx = _make_ctx(notify_on_close=False, min_seconds=10, initial={
        "ws:ws1:current": {
            "opened_at_ms": opened_at_ms,
            "sessions_created": 2,
            "commits_created": 1,
        }
    })
    asyncio.run(on_closed(ctx, WorkspaceClosedPayload(workspace_id="ws1")))
    assert ctx._notifies == []
