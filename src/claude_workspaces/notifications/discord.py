"""DiscordWebhookAdapter — espelha notificações da central num canal Discord.

Escuta `notification_added` do `NotificationService` e, para cada notificação
relevante, faz um POST JSON no webhook configurado (formato
https://discord.com/api/webhooks/<id>/<token>), montando um *embed* com
título, corpo, cor por prioridade e o nome do workspace no rodapé.

Regras (alinhadas ao DesktopNotifierAdapter):
- Só entrega quando `enabled=True` e há uma URL de webhook.
- Respeita os mutes por tipo da central (`muted_kinds`) — o que o
  `NotificationService` já filtra antes de emitir, então aqui só checamos
  o on/off e a URL.
- Pula notificações já `seen`/`dismissed`.
- O POST roda em thread separada (urllib, sem dependência externa), igual
  ao resto do projeto — a UI nunca bloqueia esperando o Discord.

Quem decide *o que* notificar continua sendo o NotificationService (cooldown,
mute, dedup). Este adapter só decide *como entregar* no Discord.
"""
from __future__ import annotations

import json
import logging
import threading

from PySide6.QtCore import QObject

from .service import NotificationService
from .types import Notification, NotificationPriority

log = logging.getLogger(__name__)

# Cores (decimal) dos embeds por prioridade — padrão Discord.
_PRIORITY_COLOR = {
    NotificationPriority.LOW: 0x95A5A6,       # cinza
    NotificationPriority.NORMAL: 0x3498DB,    # azul
    NotificationPriority.HIGH: 0xE67E22,      # laranja
    NotificationPriority.CRITICAL: 0xE74C3C,  # vermelho
}

_HTTP_TIMEOUT_SECONDS = 10


def send_webhook(url: str, payload: dict, *, timeout: int = _HTTP_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """POST síncrono do payload no webhook. Retorna (ok, mensagem).

    Não levanta exceção — devolve (False, motivo) em qualquer falha pra que
    o chamador (botão "Testar") possa exibir o erro. Roda no thread atual,
    então o chamador deve cuidar de não bloquear a UI.
    """
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "claude-workspaces"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            # Discord responde 204 No Content em sucesso.
            if 200 <= resp.status < 300:
                return True, f"HTTP {resp.status}"
            return False, f"HTTP {resp.status}"
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return False, f"HTTP {e.code} {detail}".strip()
    except URLError as e:
        return False, f"Falha de conexão: {e.reason}"
    except Exception as e:  # pragma: no cover - defensivo
        return False, f"Erro: {e}"


def build_embed_payload(
    *,
    title: str,
    body: str,
    priority: int = NotificationPriority.NORMAL,
    workspace: str | None = None,
) -> dict:
    """Monta o payload de embed do Discord pra uma notificação."""
    embed: dict = {
        "title": (title or "(sem título)")[:256],
        "color": _PRIORITY_COLOR.get(priority, 0x3498DB),
    }
    if body:
        embed["description"] = body[:4096]
    if workspace:
        embed["footer"] = {"text": workspace[:2048]}
    return {"embeds": [embed]}


class DiscordWebhookAdapter(QObject):
    """Plugá-vel: instancie com o service e provedores de config; pronto.

    `enabled_provider` e `url_provider` são callables lidos a cada
    notificação, pra que mudanças nas settings (sem recriar o adapter)
    passem a valer na hora.
    """

    def __init__(
        self,
        service: NotificationService,
        *,
        enabled_provider,
        url_provider,
        workspace_name_provider=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._enabled_provider = enabled_provider
        self._url_provider = url_provider
        # Callable[[str|None], str|None] — resolve workspace_id -> nome legível
        # pro rodapé do embed. Opcional.
        self._workspace_name_provider = workspace_name_provider
        service.notification_added.connect(self._on_added)

    def _on_added(self, n: Notification) -> None:
        try:
            if not self._enabled_provider():
                return
            url = (self._url_provider() or "").strip()
            if not url:
                return
            if n.seen or n.dismissed:
                return
        except Exception:
            log.debug("checagem de config do Discord falhou", exc_info=True)
            return

        workspace = None
        if self._workspace_name_provider is not None:
            try:
                workspace = self._workspace_name_provider(n.workspace_id)
            except Exception:
                workspace = None

        payload = build_embed_payload(
            title=n.title,
            body=n.body or "",
            priority=n.priority,
            workspace=workspace,
        )
        # Dispara em thread daemon — não queremos bloquear o thread da UI
        # nem manter a app viva por causa de um POST pendente.
        threading.Thread(
            target=self._deliver,
            args=(url, payload),
            daemon=True,
            name="discord-webhook",
        ).start()

    def _deliver(self, url: str, payload: dict) -> None:
        ok, msg = send_webhook(url, payload)
        if not ok:
            log.warning("Webhook do Discord falhou: %s", msg)


__all__ = ["DiscordWebhookAdapter", "send_webhook", "build_embed_payload"]
