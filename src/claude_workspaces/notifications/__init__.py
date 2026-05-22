"""Sistema centralizado de notificações.

Camadas:

- `types`: dataclass `Notification` + enums `NotificationKind`/`NotificationPriority`.
- `store`: estado em memória sem Qt (testável puro).
- `persistence`: leitura/escrita JSON atômica com fallback anti-corrupção.
- `service`: `NotificationService` (QObject) com sinais Qt — fachada usada
  por emissores e pela UI.

Em commits subsequentes serão adicionados:

- `desktop` (`DesktopNotifier` adapter que escuta `notification_added`),
- `tray` (`TrayNotifier` resumo no QSystemTrayIcon),
- `center` (UI `NotificationCenter` com filtros e ações rápidas).
"""
from __future__ import annotations

from .service import NotificationService
from .store import NotificationStore
from .types import (
    ACTIONABLE_KINDS,
    DEFAULT_PRIORITY,
    Notification,
    NotificationKind,
    NotificationPriority,
)

__all__ = [
    "ACTIONABLE_KINDS",
    "DEFAULT_PRIORITY",
    "Notification",
    "NotificationKind",
    "NotificationPriority",
    "NotificationService",
    "NotificationStore",
]
