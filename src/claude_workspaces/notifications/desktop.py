"""DesktopNotifierAdapter — ponte entre NotificationService e o wrapper D-Bus.

Escuta `notification_added` / `notification_changed` e despacha um popup
nativo via `services.desktop_notifier.DesktopNotifier`, com regras:

- Não notifica se o app está em foco (usuário acabou de ver na tela).
- Não notifica notificações já `seen=True` ou `dismissed=True`.
- Não notifica quando `desktop_enabled=False` nas preferências.
- Reaproveita `replaces_id` por `dedup_key`, evitando empilhar banner.
- Mapeia `priority → urgency` D-Bus (LOW=0, NORMAL=1, HIGH/CRITICAL=2).
- Notif CRÍTICA é resident (não some no click) e ganha ação "Abrir".

Quem decide *o que* notificar é o `NotificationService` (cooldown, mute,
dedup). Quem decide *como entregar* (popup, som, sticky) é esse adapter.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..services.desktop_notifier import DesktopNotifier
from .service import NotificationService
from .types import Notification, NotificationPriority

log = logging.getLogger(__name__)


class DesktopNotifierAdapter(QObject):
    """Plugá-vel: instancie com o service e o desktop notifier; pronto."""

    # emitido quando o usuário clica numa ação ("open") — main window foca.
    open_target_requested = Signal(object)  # Notification

    def __init__(
        self,
        service: NotificationService,
        desktop: DesktopNotifier,
        *,
        is_app_focused: callable,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._desktop = desktop
        self._is_app_focused = is_app_focused
        # dedup_key → note_id D-Bus ativo (pra replaces_id).
        self._active: dict[str, int] = {}

        service.notification_added.connect(self._on_added)
        service.notification_changed.connect(self._on_changed)
        service.notification_removed.connect(self._on_removed_id)

    def _on_added(self, notification: Notification) -> None:
        self._maybe_deliver(notification, allow_when_focused=False)

    def _on_changed(self, notification: Notification) -> None:
        # Só re-emite popup quando uma notif relevante segue não-vista
        # (ex.: usuário clicou "Adiar"; reminder vai ressuscitar mais tarde).
        # Se a entrada virou seen/dismissed, fecha o banner ativo.
        if notification.seen or notification.dismissed:
            self._close_for(notification)
            return

    def _on_removed_id(self, notif_id: str) -> None:
        # Não conseguimos achar a entrada pelo id (já saiu do store), então
        # iteramos: como o map é pequeno, é barato.
        pending: list[str] = []
        for key, nid in self._active.items():
            if key.startswith(f"_id:{notif_id}"):
                pending.append(key)
        for key in pending:
            try:
                self._desktop.close(self._active.pop(key))
            except Exception:
                log.debug("close falhou", exc_info=True)

    def _maybe_deliver(
        self, n: Notification, *, allow_when_focused: bool
    ) -> None:
        if not self._desktop.available:
            return
        prefs = self._service.preferences
        if not prefs.get("desktop_enabled", True):
            return
        if n.seen or n.dismissed:
            return
        if not allow_when_focused:
            try:
                if self._is_app_focused():
                    log.debug("popup suprimido — app em foco (notif=%s)", n.id)
                    return
            except Exception:
                log.debug("is_app_focused falhou", exc_info=True)

        urgency = NotificationPriority.to_urgency(n.priority)
        # CRITICAL e HIGH ganham timeout longo (sticky) e action "Abrir".
        sticky = n.priority in (NotificationPriority.HIGH, NotificationPriority.CRITICAL)
        actions: list[tuple[str, str]] = []
        if n.workspace_id or n.session_id or n.tab_id is not None:
            actions.append(("open", "Abrir"))
        if n.is_actionable():
            actions.append(("snooze5", "Adiar 5m"))
            actions.append(("seen", "Já vi"))

        key = n.dedup_key or f"_id:{n.id}"
        prev = self._active.get(key, 0)
        try:
            nid = self._desktop.notify(
                title=n.title,
                body=n.body or "",
                actions=actions,
                on_action=lambda action_key, _n=n: self._handle_action(_n, action_key),
                timeout_ms=0 if sticky else 6000,
                replaces_id=prev,
                urgency=urgency,
                desktop_entry="claude-workspaces",
                resident=sticky,
                transient=False if sticky else None,
            )
        except Exception:
            log.exception("DesktopNotifier.notify falhou")
            return
        if nid:
            self._active[key] = nid

    def _close_for(self, n: Notification) -> None:
        key = n.dedup_key or f"_id:{n.id}"
        nid = self._active.pop(key, None)
        if nid:
            try:
                self._desktop.close(nid)
            except Exception:
                log.debug("close falhou", exc_info=True)

    def _handle_action(self, n: Notification, action_key: str) -> None:
        if action_key == "open":
            self._service.mark_seen(n.id)
            self.open_target_requested.emit(n)
        elif action_key == "snooze5":
            self._service.snooze(n.id, 5 * 60)
        elif action_key == "seen":
            self._service.mark_seen(n.id)


__all__ = ["DesktopNotifierAdapter"]
