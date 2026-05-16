"""Cola entre o app e o subsistema de plugins.

Responsabilidades:
- Inicia EventBus + PluginRegistry + PluginRuntime no startup do app.
- Provê `ctx_factory`: constrói o `BaseContext` concreto pra cada plugin,
  com permissões já aplicadas.
- Expõe `publish(event, payload)` para o resto do app despachar eventos
  do catálogo da seção 7 da spec.

A implementação das sub-APIs do ctx é mínima nesta primeira entrega:
- `log`: escreve em `<install_dir>/.logs/YYYY-MM-DD.log`
- `storage`: usa `PluginStorage` direto
- `ui.notify/toast`: emite sinal Qt que MainWindow ou outro receptor pode
  pegar via `host.notifications.connect(...)`
- `workspaces`, `sessions`, `fs`, `http`, `config`: stubs que levantam
  `NotImplementedError` — ligados conforme features forem usadas

Isso permite que plugins de hook simples (notificação por evento) já
funcionem; APIs mais ricas são plugadas incrementalmente sem mudar a spec."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..plugin_api import BaseContext  # noqa: F401 — usado em type hints
from ..plugins import (
    EventBus,
    InstalledPlugin,
    PluginRegistry,
    PluginRuntime,
    PluginStorage,
    is_known_event,
)

log = logging.getLogger(__name__)


# -------------------- APIs mínimas ----------------------------------------


class _PluginLog:
    """log.info/warn/error → arquivo do plugin + logger do host."""

    def __init__(self, install_dir: Path, plugin_id: str) -> None:
        self._dir = install_dir / ".logs"
        self._id = plugin_id

    def _write(self, level: str, msg: str, data: dict[str, Any]) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            f = self._dir / f"{datetime.now():%Y-%m-%d}.log"
            ts = datetime.now().isoformat(timespec="seconds")
            payload = f" {data}" if data else ""
            with f.open("a", encoding="utf-8") as fp:
                fp.write(f"{ts} [{level}] {msg}{payload}\n")
        except OSError:
            pass  # silencioso por design — log nunca derruba handler
        log.log(
            {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}[
                level
            ],
            "[%s] %s%s",
            self._id,
            msg,
            f" {data}" if data else "",
        )

    def info(self, msg: str, **data: Any) -> None:
        self._write("info", msg, data)

    def warn(self, msg: str, **data: Any) -> None:
        self._write("warn", msg, data)

    def error(self, msg: str, **data: Any) -> None:
        self._write("error", msg, data)


class _PluginConfig:
    """Lê config do plugin a partir do manifesto (valor default).

    A v2 ainda não tem override do usuário por plugin — quando vier, a
    fonte muda pra um JSON em `<install_dir>/.state/config.json` mas a
    API pública não."""

    def __init__(self, inst: InstalledPlugin) -> None:
        self._defaults: dict[str, Any] = {f.key: f.default for f in inst.manifest.config}
        self._listeners: list[Callable[[str, Any], None]] = []

    async def get(self, key: str) -> Any:
        return self._defaults.get(key)

    def on_change(self, cb: Callable[[str, Any], None]):
        self._listeners.append(cb)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(cb)
            except ValueError:
                pass

        return unsubscribe


class _NotImplementedAPI:
    """Stub que levanta NotImplementedError em qualquer chamada async."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str):
        async def _stub(*args: Any, **kwargs: Any):
            raise NotImplementedError(
                f"ctx.{self._name}.{attr} ainda não está conectado no host"
            )

        return _stub


class _PluginUI:
    """ui.notify/toast/badge — emitem sinal Qt que o host pode escutar."""

    def __init__(self, host: "PluginHost", plugin_id: str) -> None:
        self._host = host
        self._id = plugin_id

    async def notify(self, *, title: str, body: str, sound: bool = False) -> None:
        self._host.notifications.emit(self._id, "notify", {
            "title": title, "body": body, "sound": sound,
        })

    async def toast(self, *, message: str, level: str = "info") -> None:
        self._host.notifications.emit(self._id, "toast", {
            "message": message, "level": level,
        })

    async def badge(self, *, count: int | None = None) -> None:
        self._host.notifications.emit(self._id, "badge", {"count": count})


class _AsyncStorage:
    """Adapta `PluginStorage` (sync) para a API async esperada pela spec."""

    def __init__(self, base: PluginStorage) -> None:
        self._b = base

    async def get(self, key: str):
        return self._b.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._b.set(key, value)

    async def delete(self, key: str) -> None:
        self._b.delete(key)

    async def clear(self) -> None:
        self._b.clear()


# -------------------- ctx concreto -----------------------------------------


class _Ctx:
    """`BaseContext` concreto. Não usa Protocol pra não exigir runtime_checkable
    em runtime — o duck typing dos handlers basta."""

    def __init__(self, host: "PluginHost", inst: InstalledPlugin) -> None:
        self.log = _PluginLog(inst.install_dir, inst.id)
        self.config = _PluginConfig(inst)
        self.storage = _AsyncStorage(inst.storage())
        self.ui = _PluginUI(host, inst.id)
        # APIs ainda não plugadas — stubs honestos
        self.workspaces = _NotImplementedAPI("workspaces")
        self.sessions = _NotImplementedAPI("sessions")
        self.fs = _NotImplementedAPI("fs")
        self.http = _NotImplementedAPI("http")


# -------------------- Host -------------------------------------------------


class PluginHost(QObject):
    """Singleton lazy criado pelo MainWindow.

    Sinais expostos:
    - `notifications(plugin_id, kind, payload)`: ui.notify/toast/badge
    """

    notifications = Signal(str, str, dict)

    def __init__(self) -> None:
        super().__init__()
        self.registry = PluginRegistry()
        self.bus = EventBus()
        # Loop dedicado pra rodar handlers — não bloqueia a GUI nem disputa
        # com o loop principal (que pode nem existir em Qt puro).
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="plugin-host"
        )
        self._thread.start()
        self.runtime = PluginRuntime(
            self.registry,
            self.bus,
            ctx_factory=lambda inst: _Ctx(self, inst),
            loop=self._loop,
        )
        # Carrega tudo que estiver enabled
        errs_by_plugin = self.runtime.load_all()
        for pid, errs in errs_by_plugin.items():
            for e in errs:
                log.warning("Plugin %s: %s", pid, e)

    def publish(self, event: str, payload: dict[str, Any]) -> int:
        """Despacha um evento do catálogo (seção 7) para todos plugins."""
        if not is_known_event(event):
            log.warning("Evento desconhecido publicado: %s", event)
        return self.bus.publish(event, payload)

    def shutdown(self) -> None:
        """Chamado no fechar do app — descarrega plugins e para o loop."""
        try:
            self.runtime.unload_all()
        except Exception:  # noqa: BLE001
            log.exception("Falha descarregando plugins")
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
            self._loop.close()
        except Exception:  # noqa: BLE001
            log.exception("Falha parando loop do plugin host")
