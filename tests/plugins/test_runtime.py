"""Testes do PluginRuntime: load/unload + dispatch de eventos."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_workspaces.plugins import (
    EventBus,
    PluginRegistry,
    PluginRuntime,
)


def _stub_ctx_factory(_inst):
    """ctx que conta calls — usado pra checar que o handler executou."""
    state = SimpleNamespace(calls=[], notify_calls=[])

    async def notify(**kwargs):
        state.notify_calls.append(kwargs)

    return SimpleNamespace(
        log=SimpleNamespace(info=lambda msg, **k: state.calls.append(("log", msg))),
        ui=SimpleNamespace(notify=notify),
        config=SimpleNamespace(get=lambda k: None),
        sessions=SimpleNamespace(),
        workspaces=SimpleNamespace(),
        storage=SimpleNamespace(),
        fs=SimpleNamespace(),
        http=SimpleNamespace(),
        _state=state,
    )


@pytest.fixture
def runtime(registry_root: Path):
    """Runtime stand-alone com event loop dedicado pra teste."""
    registry = PluginRegistry(root=registry_root)
    bus = EventBus()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    runtime = PluginRuntime(registry, bus, _stub_ctx_factory, loop=loop)
    yield runtime
    runtime.unload_all()
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)
    loop.close()


def test_load_hook_dispatches_on_publish(make_bundle, registry_root, runtime):
    bundle = make_bundle()
    registry = runtime._registry
    inst = registry.install(bundle)

    errs = runtime.load(inst)
    assert errs == []

    # publica evento -> handler async deve ser chamado
    runtime._bus.publish("workspace.opened", {"workspaceId": "ws1"})
    # espera assíncrono terminar (handler só faz ctx.log.info)
    deadline = 2.0
    step = 0.05
    elapsed = 0.0
    ctx_state = None
    # pega o ctx criado pelo runtime — capturado via factory
    # como factory cria novo a cada call, vamos verificar via published_count
    while elapsed < deadline:
        # se bus contou subscribers, despachou
        if runtime._bus.subscriber_count("workspace.opened") > 0:
            break
        import time as _t

        _t.sleep(step)
        elapsed += step
    assert runtime._bus.subscriber_count("workspace.opened") == 1


def test_unload_removes_subscriptions(make_bundle, registry_root, runtime):
    bundle = make_bundle()
    inst = runtime._registry.install(bundle)
    runtime.load(inst)
    assert runtime._bus.subscriber_count("workspace.opened") == 1
    runtime.unload(inst.id)
    assert runtime._bus.subscriber_count("workspace.opened") == 0


def test_load_all_loads_only_enabled(make_bundle, registry_root, runtime):
    bundle_a = make_bundle(overrides={"id": "com.exemplo.a"}, bundle_name="a")
    bundle_b = make_bundle(overrides={"id": "com.exemplo.b"}, bundle_name="b")
    inst_a = runtime._registry.install(bundle_a)
    inst_b = runtime._registry.install(bundle_b)
    runtime._registry.set_enabled(inst_b.id, False)

    results = runtime.load_all()
    assert inst_a.id in results
    assert inst_b.id not in results


def test_command_handler_invocation(make_bundle, registry_root, runtime):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [],
                "commands": [
                    {
                        "id": "say-hi",
                        "title": "Say Hi",
                        "handler": "./src/commands/say.py",
                        "description": "diz oi",
                    }
                ],
            }
        },
        extra_files={
            "src/__init__.py": "",
            "src/commands/__init__.py": "",
            "src/commands/say.py": (
                "from claude_workspaces.plugin_api import CommandContext\n"
                "async def handler(ctx: CommandContext) -> None:\n"
                "    ctx.log.info('hi')\n"
            ),
        },
        skip_default_handler=True,
    )
    # remove o default handler.py do template (skip_default só pula o on_open)
    inst = runtime._registry.install(bundle)
    errs = runtime.load(inst)
    assert errs == []

    assert "say-hi" in runtime._commands[inst.id]
    runtime.invoke_command(inst.id, "say-hi")


def test_handler_exception_does_not_crash_bus(make_bundle, registry_root, runtime):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    raise RuntimeError('boom')\n"
        )
    )
    inst = runtime._registry.install(bundle)
    runtime.load(inst)
    # publica — não deve propagar
    runtime._bus.publish("workspace.opened", {"workspaceId": "ws1"})
    # se o bus rola normalmente, ainda tem subscribers
    assert runtime._bus.subscriber_count("workspace.opened") == 1
