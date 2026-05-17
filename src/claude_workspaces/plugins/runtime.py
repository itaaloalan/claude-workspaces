"""Runtime: carrega plugins instalados e executa handlers.

Importa cada bundle como um pacote Python usando `importlib.util` com
`spec.loader.exec_module`. Cada plugin recebe um nome de módulo único
(`_plugin_<id_sanitized>`) pra não colidir com o resto do app.

Fluxo:
1. `PluginRuntime(registry, event_bus, ctx_factory)`
2. `.load_all()` → carrega todos os enabled, descobre handlers, registra hooks
3. host publica eventos no `event_bus` (já há agendamento de throttle/debounce
   embutido no bus); o runtime traduz `dict payload → dataclass` e despacha
   na função `async def handler` via asyncio.
4. `.unload_all()` no shutdown

O sandbox aqui é só "respeito ao contrato": o analyzer já barrou imports
perigosos no install; em runtime, plugins se autocontrolam dentro do que a
API expõe."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import re
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from .. import plugin_api
from .errors import PluginError
from .events import EventBus
from .manifest import Hook
from .registry import InstalledPlugin, PluginRegistry

log = logging.getLogger(__name__)


# Timeouts da spec (seções 4.1, 4.2). Handler que estoura é cancelado e
# logado — host não derruba.
HOOK_TIMEOUT_S = 5.0
COMMAND_TIMEOUT_S = 30.0

_PAYLOAD_FOR_EVENT: dict[str, type] = {
    "session.created": plugin_api.SessionCreatedPayload,
    "session.status-changed": plugin_api.SessionStatusChangedPayload,
    "session.message-sent": plugin_api.SessionMessageSentPayload,
    "session.completed": plugin_api.SessionCompletedPayload,
    "workspace.opened": plugin_api.WorkspaceOpenedPayload,
    "workspace.closed": plugin_api.WorkspaceClosedPayload,
    "commit.created": plugin_api.CommitCreatedPayload,
    "plugin.config-changed": plugin_api.PluginConfigChangedPayload,
}


CtxFactory = Callable[[InstalledPlugin], plugin_api.BaseContext]
"""Callable que recebe um plugin instalado e devolve o `ctx` já com
permissões aplicadas. O host fornece isso (vê `services/plugin_host.py`)."""


_ID_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _module_name_for(plugin_id: str) -> str:
    return "_plugin_" + _ID_SAFE_RE.sub("_", plugin_id)


def _load_module(install_dir: Path, module_name: str) -> ModuleType:
    """Importa o bundle como pacote raiz `module_name`.

    Faz isso registrando `module_name` apontando pro `__init__.py` em
    `install_dir/src/` e cada subpacote (commands/hooks/panels) como
    `module_name.<sub>`."""
    src_dir = install_dir / "src"
    init = src_dir / "__init__.py"
    if not init.exists():
        # cria implícito pra plugins simples — não escreve em disco, só
        # registra um módulo vazio
        mod = ModuleType(module_name)
        mod.__path__ = [str(src_dir)]  # type: ignore[attr-defined]
        sys.modules[module_name] = mod
        return mod
    spec = importlib.util.spec_from_file_location(
        module_name,
        init,
        submodule_search_locations=[str(src_dir)],
    )
    if spec is None or spec.loader is None:
        raise PluginError(f"Não consegui importar {install_dir}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_subpackage(
    name: str, dir_path: Path
) -> ModuleType:
    """Registra/retorna `name` como pacote apontando pra `dir_path`.

    Se houver `__init__.py` no diretório, executa-o; senão cria um módulo
    vazio com `__path__` apontando pro diretório (namespace package)."""
    if name in sys.modules:
        return sys.modules[name]
    init = dir_path / "__init__.py"
    if init.exists():
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[str(dir_path)]
        )
        if spec is None or spec.loader is None:
            raise PluginError(f"Não consegui criar spec para {name}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    pkg = ModuleType(name)
    pkg.__path__ = [str(dir_path)]  # type: ignore[attr-defined]
    sys.modules[name] = pkg
    return pkg


def _load_handler_module(
    install_dir: Path, root_module: str, handler_path: str
) -> ModuleType:
    """`./src/hooks/x.py` → módulo `root_module.hooks.x`."""
    rel = handler_path[2:] if handler_path.startswith("./") else handler_path
    parts = rel.split("/")
    if parts[0] != "src":
        raise PluginError(f"handler fora de src/: {handler_path}")
    full_path = install_dir / Path(rel)
    if not full_path.is_file():
        raise PluginError(f"handler não existe: {handler_path}")

    # Garante cada subpacote intermediário: root_module, root_module.hooks, ...
    sub_parts = parts[1:-1]  # tudo entre 'src' e o arquivo final
    qualified_parts = [root_module]
    current_dir = install_dir / "src"
    for segment in sub_parts:
        qualified_parts.append(segment)
        current_dir = current_dir / segment
        _ensure_subpackage(".".join(qualified_parts), current_dir)

    leaf_name = parts[-1].removesuffix(".py")
    full_name = ".".join(qualified_parts + [leaf_name])
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, full_path)
    if spec is None or spec.loader is None:
        raise PluginError(f"Não consegui carregar {handler_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_async_callable(obj: Any, kind: str, plugin_id: str) -> Callable:
    if not callable(obj):
        raise PluginError(
            f"{plugin_id}: handler de {kind} não é callable ({type(obj).__name__})"
        )
    if kind in {"command", "hook"} and not inspect.iscoroutinefunction(obj):
        raise PluginError(
            f"{plugin_id}: handler de {kind} precisa ser `async def`"
        )
    return obj


def _payload_from_dict(event: str, raw: dict[str, Any]) -> Any:
    cls = _PAYLOAD_FOR_EVENT.get(event)
    if cls is None:
        return raw  # evento custom — entrega o dict cru
    # Mapeia camelCase / snake_case do payload para os fields da dataclass
    field_names = set(getattr(cls, "__dataclass_fields__", {}).keys())
    norm: dict[str, Any] = {}
    for k, v in raw.items():
        snake = _camel_to_snake(k)
        if snake in field_names:
            norm[snake] = v
        elif k in field_names:
            norm[k] = v
    try:
        return cls(**norm)
    except TypeError:
        # Faltou campo obrigatório — entrega o dict pra o handler ainda receber algo
        return raw


_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower()


# --------------------------- Runtime ------------------------------------


class PluginRuntime:
    """Coordena vida dos plugins. Stateless do ponto de vista do host;
    todo estado vive no registry (disco) e no event bus."""

    def __init__(
        self,
        registry: PluginRegistry,
        event_bus: EventBus,
        ctx_factory: CtxFactory,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._registry = registry
        self._bus = event_bus
        self._ctx_factory = ctx_factory
        self._loop = loop
        self._lock = threading.RLock()
        # plugin_id → list[Subscription tokens do bus]
        self._subs: dict[str, list] = {}
        # plugin_id → root ModuleType (pro unload)
        self._modules: dict[str, str] = {}
        # plugin_id → command_id → handler async
        self._commands: dict[str, dict[str, Callable]] = {}
        # plugin_id → panel_id → factory síncrona
        self._panels: dict[str, dict[str, Callable]] = {}

    # ----- load / unload ----

    def load_all(self) -> dict[str, list[str]]:
        """Carrega todos os plugins enabled. Retorna `{plugin_id: [erros]}`
        — chave existe mesmo sem erros (lista vazia)."""
        results: dict[str, list[str]] = {}
        for inst in self._registry.list_installed():
            if not inst.enabled:
                continue
            results[inst.id] = self.load(inst)
        return results

    def load(self, inst: InstalledPlugin) -> list[str]:
        with self._lock:
            if inst.id in self._modules:
                log.debug("[%s] já estava carregado — load() é no-op", inst.id)
                return []  # já carregado
            errs: list[str] = []
            module_name = _module_name_for(inst.id)
            try:
                _load_module(inst.install_dir, module_name)
            except Exception as e:  # noqa: BLE001
                log.exception(
                    "[%s] falha ao importar bundle (módulo %s, dir=%s)",
                    inst.id, module_name, inst.install_dir,
                )
                return [f"falha ao importar bundle: {e}"]
            self._modules[inst.id] = module_name

            hooks_ok = commands_ok = panels_ok = 0
            for hook in inst.manifest.hooks:
                err = self._register_hook(inst, module_name, hook)
                if err:
                    errs.append(err)
                else:
                    hooks_ok += 1
            for cmd in inst.manifest.commands:
                err = self._register_command(inst, module_name, cmd)
                if err:
                    errs.append(err)
                else:
                    commands_ok += 1
            for panel in inst.manifest.panels:
                err = self._register_panel(inst, module_name, panel)
                if err:
                    errs.append(err)
                else:
                    panels_ok += 1

            total = hooks_ok + commands_ok + panels_ok
            expected = (
                len(inst.manifest.hooks)
                + len(inst.manifest.commands)
                + len(inst.manifest.panels)
            )
            level = logging.INFO if not errs else logging.WARNING
            log.log(
                level,
                "[%s] carregado: %d/%d extensão(ões) ativas "
                "(hooks=%d, commands=%d, panels=%d) | versão=%s | erros=%d",
                inst.id,
                total,
                expected,
                hooks_ok,
                commands_ok,
                panels_ok,
                inst.manifest.version,
                len(errs),
            )
            return errs

    def unload(self, plugin_id: str) -> None:
        with self._lock:
            had_module = plugin_id in self._modules
            # cancela subs do bus
            removed_subs = self._bus.unsubscribe_plugin(plugin_id)
            self._subs.pop(plugin_id, None)
            n_cmds = len(self._commands.pop(plugin_id, {}))
            n_panels = len(self._panels.pop(plugin_id, {}))
            # remove módulos do sys.modules
            module_name = self._modules.pop(plugin_id, None)
            n_modules = 0
            if module_name:
                # remove submódulos primeiro
                to_remove = [
                    name for name in list(sys.modules)
                    if name == module_name or name.startswith(module_name + ".")
                ]
                for name in to_remove:
                    sys.modules.pop(name, None)
                n_modules = len(to_remove)
            if had_module:
                log.info(
                    "[%s] descarregado (hooks=%d, commands=%d, panels=%d, "
                    "submodules=%d)",
                    plugin_id, removed_subs, n_cmds, n_panels, n_modules,
                )
            else:
                log.debug(
                    "[%s] unload chamado mas plugin não estava carregado",
                    plugin_id,
                )

    def unload_all(self) -> None:
        with self._lock:
            for pid in list(self._modules.keys()):
                self.unload(pid)

    # ----- registros internos ----

    def _register_hook(
        self, inst: InstalledPlugin, module_name: str, hook: Hook
    ) -> str | None:
        try:
            mod = _load_handler_module(inst.install_dir, module_name, hook.handler)
        except Exception as e:  # noqa: BLE001
            log.exception(
                "[%s] hook %s não importou (event=%s)",
                inst.id, hook.handler, hook.event,
            )
            return f"hook {hook.handler}: {e}"
        try:
            fn = _ensure_async_callable(getattr(mod, "handler", None), "hook", inst.id)
        except PluginError as e:
            log.warning("[%s] hook %s descartado: %s", inst.id, hook.handler, e)
            return str(e)

        ctx = self._ctx_factory(inst)
        event = hook.event

        def dispatcher(raw_payload: dict[str, Any]) -> None:
            payload = _payload_from_dict(event, raw_payload)
            log.debug(
                "[%s] dispatch hook %s → %s",
                inst.id, event, hook.handler,
            )
            self._run_async(
                fn(ctx, payload), inst.id, event, timeout=HOOK_TIMEOUT_S
            )

        sub = self._bus.subscribe(
            inst.id,
            event,
            dispatcher,
            throttle_ms=hook.throttle_ms,
            debounce_ms=hook.debounce_ms,
        )
        self._subs.setdefault(inst.id, []).append(sub)
        rate_note = ""
        if hook.throttle_ms:
            rate_note = f" throttle={hook.throttle_ms}ms"
        elif hook.debounce_ms:
            rate_note = f" debounce={hook.debounce_ms}ms"
        log.info(
            "[%s] hook registrado: %s → %s%s",
            inst.id, event, hook.handler, rate_note,
        )
        return None

    def _register_command(self, inst: InstalledPlugin, module_name: str, cmd) -> str | None:
        try:
            mod = _load_handler_module(inst.install_dir, module_name, cmd.handler)
        except Exception as e:  # noqa: BLE001
            log.exception(
                "[%s] command %s não importou (id=%s)",
                inst.id, cmd.handler, cmd.id,
            )
            return f"command {cmd.handler}: {e}"
        try:
            fn = _ensure_async_callable(
                getattr(mod, "handler", None), "command", inst.id
            )
        except PluginError as e:
            log.warning("[%s] command %s descartado: %s", inst.id, cmd.id, e)
            return str(e)
        self._commands.setdefault(inst.id, {})[cmd.id] = fn
        log.info(
            "[%s] command registrado: %s (%s) → %s",
            inst.id, cmd.id, cmd.title, cmd.handler,
        )
        return None

    def _register_panel(self, inst: InstalledPlugin, module_name: str, panel) -> str | None:
        try:
            mod = _load_handler_module(inst.install_dir, module_name, panel.handler)
        except Exception as e:  # noqa: BLE001
            log.exception(
                "[%s] panel %s não importou (id=%s)",
                inst.id, panel.handler, panel.id,
            )
            return f"panel {panel.handler}: {e}"
        fn = getattr(mod, "handler", None)
        if not callable(fn):
            log.warning(
                "[%s] panel %r descartado: handler não é callable",
                inst.id, panel.id,
            )
            return f"{inst.id}: handler de panel {panel.id!r} não é callable"
        if inspect.iscoroutinefunction(fn):
            log.warning(
                "[%s] panel %r descartado: handler é async (panels têm que "
                "ser síncronos — retornam QWidget)",
                inst.id, panel.id,
            )
            return (
                f"{inst.id}: handler de panel {panel.id!r} precisa ser síncrono "
                f"(retorna QWidget)"
            )
        self._panels.setdefault(inst.id, {})[panel.id] = fn
        log.info(
            "[%s] panel registrado: %s slot=%s → %s "
            "(atenção: host ainda não renderiza panels — apenas registra)",
            inst.id, panel.id, panel.slot.value, panel.handler,
        )
        return None

    # ----- chamadas externas ----

    def invoke_command(self, plugin_id: str, command_id: str) -> None:
        """Chamado pela UI quando o usuário escolhe um command na paleta."""
        with self._lock:
            fn = self._commands.get(plugin_id, {}).get(command_id)
            inst = self._registry.get(plugin_id)
        if fn is None or inst is None:
            known = sorted(self._commands.get(plugin_id, {}).keys())
            log.warning(
                "invoke_command: %s/%s não encontrado (commands conhecidos pro "
                "plugin: %s; plugin no registry? %s)",
                plugin_id, command_id, known, inst is not None,
            )
            return
        log.info("[%s] invocando command %s", plugin_id, command_id)
        ctx = self._ctx_factory(inst)
        self._run_async(
            fn(ctx), plugin_id, f"command:{command_id}", timeout=COMMAND_TIMEOUT_S
        )

    def build_panel(self, plugin_id: str, panel_id: str):
        """Constrói o QWidget de um panel. Retorna None se não achar."""
        with self._lock:
            fn = self._panels.get(plugin_id, {}).get(panel_id)
            inst = self._registry.get(plugin_id)
        if fn is None or inst is None:
            log.warning(
                "build_panel: %s/%s não encontrado", plugin_id, panel_id,
            )
            return None
        ctx = self._ctx_factory(inst)
        log.debug("[%s] construindo panel %s", plugin_id, panel_id)
        try:
            return fn(ctx)
        except Exception:  # noqa: BLE001
            log.exception(
                "[%s] panel %s lançou no factory — retornando None",
                plugin_id, panel_id,
            )
            return None

    # ----- runner async ----

    def _run_async(
        self,
        coro: Awaitable,
        plugin_id: str,
        label: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Agenda uma coroutine no loop com timeout opcional.

        Tolerante a loop ausente (em testes síncronos, executa via asyncio.run).
        Erros e timeouts são logados, nunca propagados."""
        loop = self._loop or _get_running_loop_or_none()
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _safe(coro, plugin_id, label, timeout), loop
            )
            return
        try:
            asyncio.run(_safe(coro, plugin_id, label, timeout))
        except RuntimeError as e:
            log.warning(
                "Não consegui despachar %s do plugin %s: %s",
                label, plugin_id, e,
            )


async def _safe(
    coro: Awaitable, plugin_id: str, label: str, timeout: float | None = None
) -> None:
    try:
        if timeout is None:
            await coro
        else:
            await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.warning(
            "Handler do plugin %s estourou %ss em %s — cancelado",
            plugin_id, timeout, label,
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "Handler do plugin %s falhou em %s — host segue rodando",
            plugin_id, label,
        )


def _get_running_loop_or_none() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        return None
