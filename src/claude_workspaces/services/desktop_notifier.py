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

Nota sobre KDE Plasma: o Plasma 6 emite `NotificationClosed(reason=1)` assim que
a notificação sai do popup e vai pra central de notificações, mas as actions
continuam clicáveis lá. Por isso só descartamos o callback de uma entrada
quando o reason indica fechamento explícito (2/3/4) ou logo após uma ação
ter sido invocada.
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
_PENDING_MAX = 256

# Caminhos comuns dos samples do tema freedesktop. Preferimos
# canberra-gtk-play (respeita o tema atual e o volume do som-de-sistema);
# se não estiver disponível, caímos pro paplay/pw-play num .oga direto.
_FREEDESKTOP_SOUND_DIR = "/usr/share/sounds/freedesktop/stereo"


def _play_sound_async(sound_name: str) -> None:
    """Toca um sample XDG em background sem bloquear o event loop.

    Plasma 6 ignora a hint sound-name do D-Bus, então tocamos nós mesmos.
    Roda numa thread daemon que faz `subprocess.run` capturando stderr —
    se canberra/paplay falhar (ex: cache vazio, sample faltando), logamos
    em vez de engolir silenciosamente como Popen+DEVNULL fazia.
    """
    if not sound_name:
        return
    import os
    import threading

    def _worker() -> None:
        canberra = shutil.which("canberra-gtk-play")
        if canberra:
            try:
                r = subprocess.run(
                    [canberra, "-i", sound_name],
                    capture_output=True, text=True, timeout=5,
                )
                stderr = (r.stderr or "").strip()
                if r.returncode == 0:
                    # INFO (não DEBUG) pra deixar rastro no app.log; canberra
                    # às vezes loga warnings em stderr mesmo retornando 0
                    # (ex: cache do tema, sample faltando no tema atual).
                    if stderr:
                        log.info(
                            "canberra-gtk-play rc=0 mas stderr=%r (sound=%s)",
                            stderr[:200], sound_name,
                        )
                    else:
                        log.info("som tocado via canberra-gtk-play: %s", sound_name)
                    return
                log.warning(
                    "canberra-gtk-play falhou (rc=%s): stderr=%r",
                    r.returncode, stderr[:200],
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning("canberra-gtk-play erro: %s", e)
        sample = os.path.join(_FREEDESKTOP_SOUND_DIR, f"{sound_name}.oga")
        if not os.path.isfile(sample):
            log.warning("sample não encontrado: %s", sample)
            return
        for cmd in ("paplay", "pw-play"):
            bin_path = shutil.which(cmd)
            if not bin_path:
                continue
            try:
                r = subprocess.run(
                    [bin_path, sample],
                    capture_output=True, text=True, timeout=5,
                )
                stderr = (r.stderr or "").strip()
                if r.returncode == 0:
                    if stderr:
                        log.info("%s rc=0 mas stderr=%r (sample=%s)", cmd, stderr[:200], sample)
                    else:
                        log.info("som tocado via %s: %s", cmd, sample)
                    return
                log.warning(
                    "%s falhou (rc=%s): stderr=%r",
                    cmd, r.returncode, stderr[:200],
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning("%s erro: %s", cmd, e)

    threading.Thread(target=_worker, daemon=True).start()


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
        urgency: int = 1,
        desktop_entry: str | None = None,
        sound_name: str | None = None,
    ) -> int | None:
        """Dispara notificação. Retorna o id (int) ou None em falha.

        `urgency`: 0=low, 1=normal (default), 2=critical. Critical é
        sticky por padrão em GNOME/KDE — útil pra alertas de
        atenção que não devem sumir sem o usuário interagir.
        `desktop_entry`: nome do .desktop file (sem .desktop) — permite
        ao servidor (ex: KDE Plasma) achar configurações per-app no
        System Settings → Notifications → Applications.
        """
        if not self.available:
            return None
        actions = actions or []
        action_list: list[str] = []
        for key, label in actions:
            action_list.extend([key, label])
        # gdbus aceita arrays/dicts em formato GVariant via JSON-ish.
        # Usamos json.dumps pra escapar strings com segurança.
        actions_arg = json.dumps(action_list)
        # Hints D-Bus: urgency é byte; gdbus aceita literais GVariant tipo
        # `{"urgency": <byte 2>}`. Mantém vazio quando urgency=normal pra
        # não tomar decisão pelo servidor desnecessariamente.
        hint_parts: list[str] = []
        if urgency != 1:
            urgency_byte = max(0, min(2, int(urgency)))
            hint_parts.append("'urgency': <byte " + str(urgency_byte) + ">")
        if desktop_entry:
            # Escapa aspas simples pro literal GVariant
            safe = desktop_entry.replace("'", "\\'")
            hint_parts.append("'desktop-entry': <'" + safe + "'>")
        if sound_name:
            # sound-name é um nome XDG (ex: "message-new-instant"); enviamos
            # como hint pro servidor (GNOME Shell honra) e tocamos via
            # canberra-gtk-play em paralelo, porque KDE Plasma 6 ignora
            # essa hint silenciosamente — bug histórico do plasma-workspace.
            safe_snd = sound_name.replace("'", "\\'")
            hint_parts.append("'sound-name': <'" + safe_snd + "'>")
            _play_sound_async(sound_name)
        hints_arg = "{" + ", ".join(hint_parts) + "}" if hint_parts else "{}"
        log.warning(
            "DEBUG notify: urgency=%s timeout_ms=%s hints=%r replaces_id=%s actions=%d title=%r",
            urgency, timeout_ms, hints_arg, replaces_id, len(actions), title,
        )
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
                    hints_arg,
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
        # Cap simples FIFO — entradas antigas que nunca chegaram a fechamento
        # explícito (Plasma só emite reason=1) não devem ficar pendurando.
        while len(self._pending) > _PENDING_MAX:
            oldest = next(iter(self._pending))
            self._pending.pop(oldest, None)
        return note_id

    def inhibited(self) -> bool:
        """True se "Não perturbe" (DND) está ativo no servidor de notificações.

        Lê a property `Inhibited` em `org.freedesktop.Notifications` via
        `org.freedesktop.DBus.Properties.Get`. KDE Plasma 6 e GNOME Shell
        expõem essa property quando o usuário ativa DND globalmente ou
        algum app pediu `Inhibit`. Falha silenciosamente como False —
        servidores antigos não expõem a property.
        """
        if not self.available:
            return False
        try:
            proc = subprocess.run(
                [
                    self._gdbus_path or "gdbus", "call",
                    "--session",
                    "--dest", _BUS_SERVICE,
                    "--object-path", _BUS_PATH,
                    "--method", "org.freedesktop.DBus.Properties.Get",
                    _BUS_IFACE, "Inhibited",
                ],
                capture_output=True, text=True, timeout=2,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        if proc.returncode != 0:
            return False
        return "true" in proc.stdout.lower()

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
        nid = int(note_id)
        key = str(action_key)
        self.action_invoked.emit(nid, key)
        # Após invocar uma action, a notificação está prestes a fechar (reason=2).
        # Removemos pra evitar que cliques duplicados / re-entregas disparem
        # o callback mais de uma vez.
        entry = self._pending.pop(nid, None)
        if entry and entry.get("on_action"):
            try:
                entry["on_action"](key)
            except Exception:
                log.debug("on_action callback falhou", exc_info=True)

    @Slot("uint", "uint")
    def _on_notification_closed(self, note_id: int, reason: int) -> None:
        nid = int(note_id)
        self.notification_closed.emit(nid, int(reason))
        # reason=1 (expirou) no Plasma 6 acontece quando a notificação sai do
        # popup mas continua na central de notificações com as actions vivas.
        # Só descartamos o callback em fechamento explícito (>= 2).
        if int(reason) >= 2:
            entry = self._pending.pop(nid, None)
        else:
            entry = self._pending.get(nid)
        if entry and entry.get("on_closed"):
            try:
                entry["on_closed"](int(reason))
            except Exception:
                log.debug("on_closed callback falhou", exc_info=True)


__all__ = ["DesktopNotifier"]
