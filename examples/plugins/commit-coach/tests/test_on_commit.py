"""Testes do handler de commit.created."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hooks.on_commit import handler  # noqa: E402

from claude_workspaces.plugin_api import CommitCreatedPayload  # noqa: E402


def _make_ctx(
    *,
    enforce: bool = True,
    max_len: int = 72,
    warn_wip: bool = True,
):
    toasts: list[dict] = []
    logs: list[tuple[str, str, dict]] = []

    async def get_config(key: str):
        return {
            "enforce_conventional": enforce,
            "max_subject_length": max_len,
            "warn_on_wip": warn_wip,
        }[key]

    async def toast(**kwargs):
        toasts.append(kwargs)

    def log_info(msg, **data):
        logs.append(("info", msg, data))

    def log_warn(msg, **data):
        logs.append(("warn", msg, data))

    def log_error(msg, **data):
        logs.append(("error", msg, data))

    return SimpleNamespace(
        config=SimpleNamespace(get=get_config),
        ui=SimpleNamespace(toast=toast),
        log=SimpleNamespace(info=log_info, warn=log_warn, error=log_error),
        _toasts=toasts,
        _logs=logs,
    )


def _payload(msg: str, sha: str = "deadbeef00000") -> CommitCreatedPayload:
    return CommitCreatedPayload(workspace_id="ws1", sha=sha, message=msg)


def test_commit_conventional_valido_nao_dispara_toast():
    ctx = _make_ctx()
    asyncio.run(handler(ctx, _payload("feat(plugins): adiciona commit coach")))
    assert ctx._toasts == []
    assert any(level == "info" for level, *_ in ctx._logs)


def test_commit_fora_de_conventional_avisa():
    ctx = _make_ctx()
    asyncio.run(handler(ctx, _payload("ajustando algumas coisinhas")))
    assert len(ctx._toasts) == 1
    assert "Conventional" in ctx._toasts[0]["message"]


def test_tipo_desconhecido_e_apontado():
    ctx = _make_ctx()
    asyncio.run(handler(ctx, _payload("blah: alguma coisa")))
    assert len(ctx._toasts) == 1
    assert "fora da lista" in ctx._toasts[0]["message"]


def test_assunto_muito_longo_e_apontado():
    ctx = _make_ctx(enforce=False, max_len=40)
    longo = "x" * 60
    asyncio.run(handler(ctx, _payload(longo)))
    assert len(ctx._toasts) == 1
    assert "60 caracteres" in ctx._toasts[0]["message"]


def test_wip_dispara_alerta():
    ctx = _make_ctx()
    asyncio.run(handler(ctx, _payload("feat: wip do parser")))
    assert len(ctx._toasts) == 1
    assert "WIP" in ctx._toasts[0]["message"]


def test_enforce_off_aceita_qualquer_assunto():
    ctx = _make_ctx(enforce=False, warn_wip=False, max_len=200)
    asyncio.run(handler(ctx, _payload("mudei umas coisas")))
    assert ctx._toasts == []
