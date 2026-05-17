"""Notificações nativas via D-Bus (org.freedesktop.Notifications) com botões de ação.

Implementação híbrida:

- `Notify` é chamado via `gdbus` (subprocess) porque a marshalagem do PySide6
  não permite tipar `uint32` em `QDBusMessage.setArguments` (`QDBusArgument`
  no PySide6 não expõe `.add(value, type)`), e o servidor de notificações
  rejeita a chamada se `replaces_id` chegar como `int32`.
- Os sinais `ActionInvoked` e `NotificationClosed` são escutados via QtDBus
  (que funciona normalmente pra recepção).

Fallback é responsabilidade do chamador: se `available` for False ou `notify()`
devolver `None`, caia pro `QSystemTrayIcon.showMessage`.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, SLOT, Signal, Slot

try:
    from PySide6.QtDBus import (
        QDBusConnection,
        QDBusInterface,
        QDBusMessage,
    )
    _HAS_QTDBUS = True
except ImportError:  # pragma: no cover - QtDBus não vem em todo build
    _HAS_QTDBUS = False

log = logging.getLogger(__name__)

_BUS_SERVICE = "org.freedesktop.Notifications"
_BUS_PATH = "/org/freedesktop/Notifications"
_BUS_IFACE = "org.freedesktop.Notifications"

_GDBUS_ID_RE = re.compile(r"uint32\s+(\d+)")


class DesktopNotifier(QObject):
    """Wrapper sobre o serviço FDO Notifications com suporte a ações."""

    action_invoked = Signal(int, str)
    notification_closed = Signal(int, int)

    def __init__(self, app_name: str = "Claude Workspaces", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app_name = app_name
        self._iface: QDBusInterface | None = None
        self._caps: set[str] = set()
        self._pending: dict[int, dict[str, Any]] = {}
        self._connected: bool = False
        self._gdbus_path: str | None = shutil.which("gdbus")
        if _HAS_QTDBUS and self._gdbus_path:
            self._connect()

    @property
    def available(self) -> bool:
        return self._connected and self._gdbus_path is not None

    @property
    def supports_actions(self) -> bool:
        return "actions" in self._caps

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._caps)

    def _connect(self) -> None:
        try:
            bus = QDBusConnection.sessionBus()
            if not bus.isConnected():
                log.info("D-Bus session bus indisponível")
                return
            iface = QDBusInterface(_BUS_SERVICE, _BUS_PATH, _BUS_IFACE, bus)
            reply = iface.call("GetCapabilities")
            if reply.type() != QDBusMessage.MessageType.ReplyMessage:
                log.info(
                    "Serviço %s não respondeu GetCapabilities: %s",
                    _BUS_SERVICE, reply.errorMessage(),
                )
                return
            args = reply.arguments()
            if args and isinstance(args[0], list):
                self._caps = {str(c) for c in args[0]}
            self._iface = iface
            ok_a = bus.connect(
                _BUS_SERVICE, _BUS_PATH, _BUS_IFACE, "ActionInvoked", "us",
                self, SLOT("_on_action_invoked(uint,QString)"),
            )
            ok_c = bus.connect(
                _BUS_SERVICE, _BUS_PATH, _BUS_IFACE, "NotificationClosed", "uu",
                self, SLOT("_on_notification_closed(uint,uint)"),
            )
            if not (ok_a and ok_c):
                log.debug("Falha ao registrar handlers D-Bus (a=%s c=%s)", ok_a, ok_c)
                return
            self._connected = True
        except Exception:
            log.debug("Falha ao conectar ao serviço de notificações", exc_info=True)
            self._iface = None
            self._connected = False

    def notify(
        self,
        title: str,
        body: str,
        *,
        actions: list[tuple[str, str]] | None = None,
        on_action: Callable[[str], None] | None = None,
        on_closed: Callable[[int], None] | None = None,
        icon: str = "",
        timeout_ms: int = 6000,
        replaces_id: int = 0,
    ) -> int | None:
        """Dispara notificação. Retorna o id (int) ou None em falha."""
        if not self.available:
            return None
        actions = actions or []
        action_list: list[str] = []
        for key, label in actions:
            action_list.extend([key, label])
        # gdbus aceita arrays/dicts em formato GVariant via JSON-ish.
        # Usamos json.dumps pra escapar strings com segurança.
        actions_arg = json.dumps(action_list)
        try:
            proc = subprocess.run(
                [
                    self._gdbus_path or "gdbus", "call",
                    "--session",
                    "--dest", _BUS_SERVICE,
                    "--object-path", _BUS_PATH,
                    "--method", f"{_BUS_IFACE}.Notify",
                    self._app_name,
                    str(int(replaces_id)),
                    icon,
                    title,
                    body,
                    actions_arg,
                    "{}",
                    str(int(timeout_ms)),
                ],
                capture_output=True, text=True, timeout=3,
            )
        except (subprocess.TimeoutExpired, OSError):
            log.debug("gdbus call timeout/erro", exc_info=True)
            return None
        if proc.returncode != 0:
            log.debug("gdbus Notify falhou: %s", proc.stderr.strip())
            return None
        m = _GDBUS_ID_RE.search(proc.stdout)
        if not m:
            log.debug("Não consegui parsear id em: %r", proc.stdout)
            return None
        note_id = int(m.group(1))
        self._pending[note_id] = {
            "on_action": on_action,
            "on_closed": on_closed,
        }
        return note_id

    def close(self, note_id: int) -> None:
        if not self.available or note_id <= 0:
            return
        try:
            subprocess.run(
                [
                    self._gdbus_path or "gdbus", "call",
                    "--session",
                    "--dest", _BUS_SERVICE,
                    "--object-path", _BUS_PATH,
                    "--method", f"{_BUS_IFACE}.CloseNotification",
                    str(int(note_id)),
                ],
                capture_output=True, timeout=2,
            )
        except (subprocess.TimeoutExpired, OSError):
            log.debug("CloseNotification falhou", exc_info=True)

    @Slot("uint", str)
    def _on_action_invoked(self, note_id: int, action_key: str) -> None:
        self.action_invoked.emit(int(note_id), str(action_key))
        entry = self._pending.get(int(note_id))
        if entry and entry.get("on_action"):
            try:
                entry["on_action"](str(action_key))
            except Exception:
                log.debug("on_action callback falhou", exc_info=True)

    @Slot("uint", "uint")
    def _on_notification_closed(self, note_id: int, reason: int) -> None:
        nid = int(note_id)
        self.notification_closed.emit(nid, int(reason))
        entry = self._pending.pop(nid, None)
        if entry and entry.get("on_closed"):
            try:
                entry["on_closed"](int(reason))
            except Exception:
                log.debug("on_closed callback falhou", exc_info=True)


__all__ = ["DesktopNotifier"]
