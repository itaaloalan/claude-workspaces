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
import time
from collections.abc import Callable
from typing import Any

# Mapa reason → nome legível pro log (spec FDO §Signals.NotificationClosed).
# 1=expired (timeout do servidor), 2=dismissed (usuário fechou), 3=closed
# (CloseNotification chamado), 4=undefined/reserved.
_CLOSE_REASONS = {1: "expired", 2: "dismissed", 3: "closed_api", 4: "undefined"}

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
    Ordem: paplay/pw-play (role "music", mesmo canal do áudio normal) ANTES
    de canberra-gtk-play. canberra usa o role "event-sounds" do PA/PipeWire
    que tipicamente fica mutado no KDE Plasma — exit 0 sem som de verdade.
    """
    if not sound_name:
        return
    import os
    import threading

    def _worker() -> None:
        sample = os.path.join(_FREEDESKTOP_SOUND_DIR, f"{sound_name}.oga")
        if os.path.isfile(sample):
            for cmd in ("pw-play", "paplay"):
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
        else:
            log.warning("sample não encontrado: %s", sample)
        canberra = shutil.which("canberra-gtk-play")
        if canberra:
            try:
                r = subprocess.run(
                    [canberra, "-i", sound_name],
                    capture_output=True, text=True, timeout=5,
                )
                stderr = (r.stderr or "").strip()
                if r.returncode == 0:
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
        # Timestamp (monotonic) de quando cada nota foi criada — usado pra
        # logar quanto tempo o popup ficou vivo ao receber NotificationClosed.
        self._created_at: dict[int, float] = {}
        # Server info (nome/vendor/versão/spec-version) — útil pra correlacionar
        # bugs específicos de implementação (KDE Plasma 6 vs GNOME Shell vs dunst).
        self._server_info: dict[str, str] = {}
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
            # GetServerInformation devolve (name, vendor, version, spec_version).
            # Logamos pra deixar rastro de qual servidor estamos falando — KDE
            # Plasma 6, GNOME Shell e dunst têm comportamentos bem diferentes
            # de hints como urgency/resident/transient.
            try:
                info_reply = iface.call("GetServerInformation")
                if info_reply.type() == QDBusMessage.MessageType.ReplyMessage:
                    info_args = info_reply.arguments()
                    if len(info_args) >= 4:
                        self._server_info = {
                            "name": str(info_args[0]),
                            "vendor": str(info_args[1]),
                            "version": str(info_args[2]),
                            "spec_version": str(info_args[3]),
                        }
                        log.info(
                            "Servidor de notificações: name=%s vendor=%s version=%s spec=%s",
                            self._server_info["name"],
                            self._server_info["vendor"],
                            self._server_info["version"],
                            self._server_info["spec_version"],
                        )
            except Exception:
                log.debug("GetServerInformation falhou", exc_info=True)
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
        resident: bool = False,
        transient: bool | None = None,
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
        if resident:
            # `resident=true` (FDO): notificação NÃO some quando uma ação é
            # invocada. KDE também usa pra manter o popup visível com actions
            # em vez de tratar como transient.
            hint_parts.append("'resident': <true>")
        if transient is not None:
            # `transient=false` força o servidor a manter na central de
            # notificações. KDE Plasma 6 lê isso pra decidir entre popup
            # transient e persistente.
            hint_parts.append("'transient': <" + ("true" if transient else "false") + ">")
        hints_arg = "{" + ", ".join(hint_parts) + "}" if hint_parts else "{}"
        # Log da chamada completa + estado do DND. Se o popup sumir cedo, esse
        # log é o ponto de partida pra investigar: confere se a hint chegou,
        # se DND não está ativo, e cruza com o NotificationClosed mais à frente
        # (pelo note_id) pra medir o tempo de vida real do banner.
        action_keys = [a[0] for a in actions]
        log.info(
            "notify enviado: title=%r urgency=%s timeout_ms=%s hints=%s "
            "replaces_id=%s actions=%s server=%s caps=%s dnd=%s",
            title, urgency, timeout_ms, hints_arg, replaces_id,
            action_keys, self._server_info.get("name", "?"),
            sorted(self._caps), self.inhibited(),
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
        self._created_at[note_id] = time.monotonic()
        log.info("notify aceito pelo servidor: note_id=%s title=%r", note_id, title)
        # Cap simples FIFO — entradas antigas que nunca chegaram a fechamento
        # explícito (Plasma só emite reason=1) não devem ficar pendurando.
        while len(self._pending) > _PENDING_MAX:
            oldest = next(iter(self._pending))
            self._pending.pop(oldest, None)
            self._created_at.pop(oldest, None)
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
        created = self._created_at.get(nid)
        age = f"{time.monotonic() - created:.2f}s" if created else "?"
        log.info("ActionInvoked: note_id=%s key=%r age=%s", nid, key, age)
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
        reason_int = int(reason)
        reason_name = _CLOSE_REASONS.get(reason_int, f"unknown({reason_int})")
        created = self._created_at.get(nid)
        age_str = f"{time.monotonic() - created:.2f}s" if created else "?"
        # INFO pra ter rastro de vida do popup. Se reason=expired com age<3s
        # significa que o servidor ignorou nosso timeout/urgency/resident
        # (típico do KDE Plasma 6 com action). Se age>>10s, deu certo.
        log.info(
            "NotificationClosed: note_id=%s reason=%s(%d) age=%s",
            nid, reason_name, reason_int, age_str,
        )
        if reason_int >= 2:
            self._created_at.pop(nid, None)
        self.notification_closed.emit(nid, reason_int)
        # reason=1 (expirou) no Plasma 6 acontece quando a notificação sai do
        # popup mas continua na central de notificações com as actions vivas.
        # Só descartamos o callback em fechamento explícito (>= 2).
        if reason_int >= 2:
            entry = self._pending.pop(nid, None)
        else:
            entry = self._pending.get(nid)
        if entry and entry.get("on_closed"):
            try:
                entry["on_closed"](int(reason))
            except Exception:
                log.debug("on_closed callback falhou", exc_info=True)


__all__ = ["DesktopNotifier"]
