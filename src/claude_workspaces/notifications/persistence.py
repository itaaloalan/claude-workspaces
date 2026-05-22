"""Persistência de notificações + preferências em JSON.

Arquivo único `notifications.json` na pasta de config do app:

    {
      "version": 1,
      "notifications": [ { ... }, ... ],
      "preferences": { ... }
    }

Estratégia anti-corrupção:

- Leitura: se o JSON estiver inválido (parse error, schema errado), move pra
  `notifications.json.corrupt-<ts>` e devolve estado default. Nunca propaga
  exceção pro chamador — o app continua subindo.
- Escrita atômica: escreve em `notifications.json.tmp` e faz `os.replace`,
  que é atômico em POSIX (e razoavelmente atômico em Windows). Evita
  truncar no meio se o processo morrer durante o write.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .types import Notification

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def default_preferences() -> dict[str, Any]:
    """Estado-padrão das preferências de notificação."""
    return {
        # toggle global do desktop notifier (D-Bus)
        "desktop_enabled": True,
        # tipos silenciados
        "muted_kinds": [],
        # workspaces silenciados (lista de workspace_id)
        "muted_workspaces": [],
        # relembrar pendências (timer que re-emite notif actionable não vista)
        "reminder_enabled": True,
        "reminder_seconds": 120,
        # cooldown anti-spam por dedup_key (não repete a mesma notif dentro desse intervalo)
        "cooldown_seconds": 60,
        # histórico máximo guardado em disco
        "history_limit": 500,
    }


def load(path: Path) -> tuple[list[Notification], dict[str, Any]]:
    """Lê o JSON. Em qualquer falha de parse/schema, arquiva e devolve default.

    Devolve `(notifications, preferences)`.
    """
    if not path.exists():
        return [], default_preferences()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("payload não é dict")
        notifs_raw = data.get("notifications", [])
        if not isinstance(notifs_raw, list):
            raise ValueError("notifications não é lista")
        notifs = [Notification.from_dict(d) for d in notifs_raw if isinstance(d, dict)]
        prefs = default_preferences()
        user_prefs = data.get("preferences") or {}
        if isinstance(user_prefs, dict):
            prefs.update({k: user_prefs[k] for k in user_prefs if k in prefs})
        return notifs, prefs
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.warning("notifications.json corrompido (%s) — arquivando e recomeçando", e)
        _archive_corrupt(path)
        return [], default_preferences()


def save(
    path: Path,
    notifications: list[Notification],
    preferences: dict[str, Any],
) -> None:
    """Escrita atômica via tmp + os.replace. Silencia erros de I/O —
    não vale matar o app por causa de notificação não persistida."""
    payload = {
        "version": SCHEMA_VERSION,
        "notifications": [n.to_dict() for n in notifications],
        "preferences": dict(preferences),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        log.exception("falha ao persistir notifications.json em %s", path)


def _archive_corrupt(path: Path) -> None:
    try:
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
        path.replace(backup)
        log.warning("backup do JSON corrompido em %s", backup)
    except OSError:
        log.exception("falha ao fazer backup de %s", path)


__all__ = ["SCHEMA_VERSION", "default_preferences", "load", "save"]
