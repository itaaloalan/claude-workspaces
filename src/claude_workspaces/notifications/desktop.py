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
        timeout_ms_provider: callable | None = None,
        is_target_visible: callable | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._desktop = desktop
        self._is_app_focused = is_app_focused
        self._timeout_ms_provider = timeout_ms_provider
        # Callable[[Notification], bool] — quando fornecida, decide a
        # supressão por foco baseada no alvo específico da notificação
        # (workspace/sessão/aba visível) em vez do app inteiro. Se a
        # notif é de um console em background, popup aparece mesmo com
        # o app focado.
        self._is_target_visible = is_target_visible
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
        for key, _nid in self._active.items():
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
            # Preferimos a checagem alvo-específica: só suprime se o tab/console
            # da notif EXATAMENTE for o que o usuário está vendo. Sem alvo
            # específico (ou callable não fornecido) cai pro is_app_focused —
            # comportamento anterior, mais conservador.
            try:
                if self._is_target_visible is not None:
                    if self._is_target_visible(n):
                        log.debug("popup suprimido — alvo já visível (notif=%s)", n.id)
                        return
                elif self._is_app_focused():
                    log.debug("popup suprimido — app em foco (notif=%s)", n.id)
                    return
            except Exception:
                log.debug("checagem de foco falhou", exc_info=True)

        # Urgency forçada em NORMAL (1) no popup do S.O. — urgency=2 (critical)
        # faz KDE/GNOME ignorarem timeout e deixarem o banner sticky, e o
        # usuário relatou notificações "presas". A prioridade real (HIGH/
        # CRITICAL) continua refletida na central in-app via cor/destaque;
        # o popup nativo é só um aviso transiente.
        urgency = min(1, NotificationPriority.to_urgency(n.priority))
        # Popup do S.O. fica sem botões e sem som — botões/som ficam só na
        # central in-app. Alguns servidores deixavam de exibir o popup quando
        # tinha action buttons, então tirar as actions destrava a entrega.
        actions: list[tuple[str, str]] = []

        key = n.dedup_key or f"_id:{n.id}"
        prev = self._active.get(key, 0)
        # Popup do S.O. sempre auto-dismiss (mesmo HIGH/CRITICAL). A central
        # in-app preserva a notificação enquanto não vista; deixar o banner
        # nativo "grudado" só polui a área de notificações do Plasma.
        timeout_ms = 10000
        if self._timeout_ms_provider is not None:
            try:
                timeout_ms = int(self._timeout_ms_provider())
            except Exception:
                log.debug("timeout_ms_provider falhou", exc_info=True)
        # Clamp: timeout_ms<=0 significa "use server default" no protocolo FDO,
        # e em alguns servidores isso = nunca expira. Forçamos pelo menos 3s
        # pra garantir o auto-dismiss do banner do S.O.
        if timeout_ms <= 0:
            timeout_ms = 10000
        try:
            nid = self._desktop.notify(
                title=n.title,
                body=n.body or "",
                actions=actions,
                on_action=lambda action_key, _n=n: self._handle_action(_n, action_key),
                timeout_ms=timeout_ms,
                replaces_id=prev,
                urgency=urgency,
                desktop_entry="claude-workspaces",
                resident=False,
                transient=True,
                suppress_sound=True,
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
