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
from .types import Notification, NotificationKind, NotificationPriority

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
        fallback_notify: callable | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._desktop = desktop
        self._is_app_focused = is_app_focused
        self._timeout_ms_provider = timeout_ms_provider
        self._fallback_notify = fallback_notify
        # Callable[[Notification], bool] — quando fornecida, decide a
        # supressão por foco baseada no alvo específico da notificação
        # (workspace/sessão/aba visível) em vez do app inteiro. Se a
        # notif é de um console em background, popup aparece mesmo com
        # o app focado.
        self._is_target_visible = is_target_visible
        # dedup_key → note_id D-Bus ativo (pra replaces_id).
        self._active: dict[str, int] = {}
        # dedup_key → (kind, title, body) já entregue — pula re-entrega quando
        # nada visual mudou (evita re-popup em occurrence-bump dentro do cooldown).
        self._last_delivered: dict[str, tuple] = {}

        service.notification_added.connect(self._on_added)
        service.notification_changed.connect(self._on_changed)
        service.notification_removed.connect(self._on_removed_id)

    def _on_added(self, notification: Notification) -> None:
        self._maybe_deliver(notification, allow_when_focused=False)

    def _on_changed(self, notification: Notification) -> None:
        # Entrada virou seen/dismissed → fecha o banner ativo.
        if notification.seen or notification.dismissed:
            self._close_for(notification)
            return
        # Senão, ATUALIZA o popup in-place (replaces_id) — é o que faz a notif
        # fixa "Trabalhando" virar "Aguardando"/"Pronto" sem empilhar.
        self._maybe_deliver(notification, allow_when_focused=False, is_update=True)

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
        self, n: Notification, *, allow_when_focused: bool, is_update: bool = False
    ) -> None:
        if not self._desktop.available:
            return
        prefs = self._service.preferences
        if not prefs.get("desktop_enabled", True):
            return
        if n.seen or n.dismissed:
            return
        key = n.dedup_key or f"_id:{n.id}"
        is_working = n.kind == NotificationKind.AGENT_WORKING
        # Atualização sem mudança visual (occurrence-bump dentro do cooldown):
        # não re-emite popup.
        snapshot = (n.kind, n.title, n.body or "")
        if is_update and self._last_delivered.get(key) == snapshot:
            return
        if not allow_when_focused:
            # Preferimos a checagem alvo-específica: só suprime se o tab/console
            # da notif EXATAMENTE for o que o usuário está vendo. Sem alvo
            # específico (ou callable não fornecido) cai pro is_app_focused —
            # comportamento anterior, mais conservador.
            try:
                suppressed = (
                    self._is_target_visible(n)
                    if self._is_target_visible is not None
                    else self._is_app_focused()
                )
            except Exception:
                log.debug("checagem de foco falhou", exc_info=True)
                suppressed = False
            if suppressed:
                # O banner fixo "Trabalhando" não deve ficar na tela enquanto o
                # usuário olha o próprio console — fecha o popup ativo.
                if is_working:
                    self._close_for(n)
                log.debug("popup suprimido — alvo já visível (notif=%s)", n.id)
                return

        # Urgency forçada em NORMAL (1) no popup do S.O. — urgency=2 (critical)
        # faz KDE/GNOME ignorarem timeout e deixarem o banner sticky, e o
        # usuário relatou notificações "presas". A prioridade real (HIGH/
        # CRITICAL) continua refletida na central in-app via cor/destaque;
        # o popup nativo é só um aviso transiente.
        urgency = min(1, NotificationPriority.to_urgency(n.priority))
        # Popup do S.O. fica sem botões e sem som — botões/som ficam só na
        # central in-app. Alguns servidores deixavam de exibir o popup quando
        # tinha action buttons, então tirar as actions destrava a entrega.
        # suppress_sound=True pede ao servidor pra não tocar som; sound_name=None
        # garante que _play_sound_async nunca seja chamado daqui.
        actions: list[tuple[str, str]] = []
        _os_sound: str | None = None  # sem som no popup nativo
        _os_suppress_sound = True

        prev = self._active.get(key, 0)
        # "Trabalhando" é FIXO: resident + sem timeout — fica na tela enquanto o
        # agente trabalha e é substituído (replaces_id) pelo estado seguinte
        # (Aguardando/Pronto), que aí sim auto-dismiss. Nunca fica preso: sempre
        # resolve quando o trabalho termina.
        if is_working:
            timeout_ms = 0  # 0 = sem expiração (resident)
            resident = True
        else:
            # Popup do S.O. auto-dismiss. A central in-app preserva a notif
            # enquanto não vista; banner nativo grudado só polui o Plasma.
            timeout_ms = 15000
            resident = False
            if self._timeout_ms_provider is not None:
                try:
                    timeout_ms = int(self._timeout_ms_provider())
                except Exception:
                    log.debug("timeout_ms_provider falhou", exc_info=True)
            # Clamp: timeout_ms<=0 = "server default" (pode nunca expirar em
            # alguns servidores) → força auto-dismiss.
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
                sound_name=_os_sound,
                resident=resident,
                transient=False,
                suppress_sound=_os_suppress_sound,
            )
        except Exception:
            log.exception("DesktopNotifier.notify falhou")
            self._fallback(n)
            return
        if nid:
            self._active[key] = nid
            self._last_delivered[key] = snapshot
        else:
            log.info("DesktopNotifier.notify não retornou id; usando fallback")
            self._fallback(n)

    def _fallback(self, n: Notification) -> None:
        if self._fallback_notify is None:
            return
        try:
            self._fallback_notify(n.title, n.body or "")
        except Exception:
            log.debug("fallback de notificação falhou", exc_info=True)

    def _close_for(self, n: Notification) -> None:
        key = n.dedup_key or f"_id:{n.id}"
        self._last_delivered.pop(key, None)
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
