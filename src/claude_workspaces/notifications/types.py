"""Tipos e prioridades do sistema de notificações.

Definições enumeradas + dataclass `Notification` que é a unidade que circula
entre emissores → `NotificationService` → `NotificationStore` → UI/tray/desktop.

Decisões intencionais:

- `kind` é `str` (não `Enum`) pra serializar como string limpa no JSON sem
  precisar de adapter. As constantes em `NotificationKind` são o vocabulário
  fechado que o app usa; valores externos (vindo de plugin) podem entrar como
  string livre sem quebrar persistência.
- `priority` segue o mesmo padrão.
- `dedup_key` (opcional) é o que `NotificationService.notify` usa pra decidir
  se a entrada nova **atualiza** uma existente (mesmo workspace+sessão+tipo)
  ao invés de empilhar duplicatas. Quem emite escolhe a granularidade.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


class NotificationKind:
    PERMISSION_REQUIRED = "permission_required"
    AGENT_WAITING = "agent_waiting"
    AGENT_WORKING = "agent_working"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_IDLE = "agent_idle"
    LONG_RUNNING = "long_running"
    COST_WARNING = "cost_warning"
    WORKSPACE_ERROR = "workspace_error"

    ALL = (
        PERMISSION_REQUIRED,
        AGENT_WAITING,
        AGENT_WORKING,
        TASK_COMPLETED,
        TASK_FAILED,
        AGENT_IDLE,
        LONG_RUNNING,
        COST_WARNING,
        WORKSPACE_ERROR,
    )


class NotificationPriority:
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

    ALL = (LOW, NORMAL, HIGH, CRITICAL)

    @staticmethod
    def to_urgency(priority: str) -> int:
        """Mapeia pra urgency D-Bus (0=low, 1=normal, 2=critical)."""
        if priority == NotificationPriority.LOW:
            return 0
        if priority == NotificationPriority.CRITICAL:
            return 2
        # high cai em urgency=2 também — KDE/GNOME tornam sticky
        if priority == NotificationPriority.HIGH:
            return 2
        return 1


# Tipos que *exigem ação* — usados pelo reminder e por filtros padrão da inbox.
ACTIONABLE_KINDS = frozenset({
    NotificationKind.PERMISSION_REQUIRED,
    NotificationKind.AGENT_WAITING,
    NotificationKind.TASK_FAILED,
    NotificationKind.WORKSPACE_ERROR,
})

# Prioridade default por tipo — emissores podem sobrescrever.
DEFAULT_PRIORITY: dict[str, str] = {
    NotificationKind.PERMISSION_REQUIRED: NotificationPriority.CRITICAL,
    NotificationKind.AGENT_WAITING: NotificationPriority.HIGH,
    NotificationKind.AGENT_WORKING: NotificationPriority.LOW,
    NotificationKind.TASK_COMPLETED: NotificationPriority.NORMAL,
    NotificationKind.TASK_FAILED: NotificationPriority.HIGH,
    NotificationKind.AGENT_IDLE: NotificationPriority.LOW,
    NotificationKind.LONG_RUNNING: NotificationPriority.NORMAL,
    NotificationKind.COST_WARNING: NotificationPriority.HIGH,
    NotificationKind.WORKSPACE_ERROR: NotificationPriority.HIGH,
}


@dataclass
class Notification:
    """Entrada do store. Imutável na prática — `mark_seen` etc. produzem cópias."""

    id: str
    kind: str
    title: str
    body: str
    priority: str = NotificationPriority.NORMAL
    workspace_id: str | None = None
    session_id: str | None = None
    # tab_id é volátil (id Python da widget) — só faz sentido na sessão atual,
    # mas guardamos pra acelerar focus quando a notif ainda é "fresca".
    tab_id: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    seen: bool = False
    dismissed: bool = False
    # epoch em que a notif sai de "snoozed" — 0 = não está adiada
    snoozed_until: float = 0.0
    # chave de dedup. Default: kind+workspace+session.
    dedup_key: str | None = None
    # contador de quantas vezes essa entrada foi "atualizada" via dedup —
    # útil pra UI mostrar "(3x)" e pra debug de ruído.
    occurrences: int = 1
    # payload extra livre (ex.: cost in USD, duration, error trace truncated).
    data: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def make(
        kind: str,
        title: str,
        body: str = "",
        *,
        priority: str | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        tab_id: int | None = None,
        dedup_key: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        prio = priority or DEFAULT_PRIORITY.get(kind, NotificationPriority.NORMAL)
        if dedup_key is None:
            # Identidade da origem: session_id quando há, senão tab_id (volátil
            # mas único por console na sessão atual). Sem esse fallback, sessões
            # diferentes do MESMO workspace compartilhavam o dedup_key — duas
            # esperando dentro do cooldown colidiam e a 2ª virava só um
            # `notification_changed` (popup não reaparecia), perdendo o alerta.
            ident = session_id or (str(tab_id) if tab_id is not None else "")
            dedup_key = f"{kind}:{workspace_id or ''}:{ident}"
        return Notification(
            id=uuid.uuid4().hex,
            kind=kind,
            title=title,
            body=body,
            priority=prio,
            workspace_id=workspace_id,
            session_id=session_id,
            tab_id=tab_id,
            dedup_key=dedup_key,
            data=dict(data or {}),
        )

    def is_actionable(self) -> bool:
        return self.kind in ACTIONABLE_KINDS

    def is_snoozed(self, *, now: float | None = None) -> bool:
        n = now if now is not None else time.time()
        return self.snoozed_until > n

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Notification:
        return Notification(
            id=str(d.get("id") or uuid.uuid4().hex),
            kind=str(d.get("kind", "")),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            priority=str(d.get("priority", NotificationPriority.NORMAL)),
            workspace_id=d.get("workspace_id"),
            session_id=d.get("session_id"),
            tab_id=d.get("tab_id"),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            seen=bool(d.get("seen", False)),
            dismissed=bool(d.get("dismissed", False)),
            snoozed_until=float(d.get("snoozed_until") or 0.0),
            dedup_key=d.get("dedup_key"),
            occurrences=int(d.get("occurrences") or 1),
            data=dict(d.get("data") or {}),
        )


__all__ = [
    "ACTIONABLE_KINDS",
    "DEFAULT_PRIORITY",
    "Notification",
    "NotificationKind",
    "NotificationPriority",
]
