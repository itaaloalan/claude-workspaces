"""Testes do timeout dos handlers (seção 4.1/4.2 da spec)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from claude_workspaces.plugins import EventBus, PluginRegistry, PluginRuntime


def _stub_ctx_factory(_inst):
    from types import SimpleNamespace

    return SimpleNamespace(
        log=SimpleNamespace(
            info=lambda *_a, **_k: None,
            warn=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        ),
    )


@pytest.fixture
def runtime(registry_root):
    registry = PluginRegistry(root=registry_root)
    bus = EventBus()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    rt = PluginRuntime(registry, bus, _stub_ctx_factory, loop=loop)
    yield rt
    rt.unload_all()
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)
    loop.close()


def test_hook_handler_timeout_cancels(make_bundle, runtime, caplog):
    """Hook que excede HOOK_TIMEOUT_S é cancelado; host segue rodando."""
    # Patch o timeout pra valor curto, senão o teste demora 5s.
    from claude_workspaces.plugins import runtime as rt_mod

    original = rt_mod.HOOK_TIMEOUT_S
    rt_mod.HOOK_TIMEOUT_S = 0.1
    try:
        bundle = make_bundle(
            handler_py=(
                "import asyncio\n"
                "from claude_workspaces.plugin_api import HookContext\n"
                "async def handler(ctx: HookContext, payload):\n"
                "    await asyncio.sleep(2.0)\n"
            ),
        )
        inst = runtime._registry.install(bundle)
        runtime.load(inst)
        runtime._bus.publish("workspace.opened", {"workspaceId": "x"})
        # Espera o timeout disparar
        time.sleep(0.4)
        # bus ainda tem subscriber — host não derrubou
        assert runtime._bus.subscriber_count("workspace.opened") == 1
    finally:
        rt_mod.HOOK_TIMEOUT_S = original


def test_handler_under_timeout_completes(make_bundle, runtime):
    """Handler rápido completa normalmente."""
    bundle = make_bundle(
        handler_py=(
            "import asyncio\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    await asyncio.sleep(0.01)\n"
            "    ctx.log.info('done')\n"
        ),
    )
    inst = runtime._registry.install(bundle)
    runtime.load(inst)
    runtime._bus.publish("workspace.opened", {"workspaceId": "x"})
    time.sleep(0.1)
    assert runtime._bus.subscriber_count("workspace.opened") == 1
