"""Consulta `/api/oauth/usage` (mesmo endpoint que o `/status` do Claude
Code) pra obter os % reais de uso do plano — assim a UI bate exatamente
com o que o claude.ai mostra, sem depender da calibração USD-baseada.

Resposta observada (campos relevantes):
  {
    "five_hour":        {"utilization": <0..100>, "resets_at": "<ISO>"},
    "seven_day":        {"utilization": <0..100>, "resets_at": "<ISO>"},
    "seven_day_opus":   {"utilization": <0..100>, "resets_at": "<ISO>"},
    "seven_day_sonnet": {"utilization": <0..100>, "resets_at": "<ISO>"}
  }

Cache de 60s pra não estourar rate limit do endpoint."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_TTL_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass
class PlanUsageBucket:
    utilization_pct: float = 0.0  # 0..100
    resets_at: datetime | None = None


@dataclass
class PlanUsageSnapshot:
    five_hour: PlanUsageBucket | None = None
    seven_day: PlanUsageBucket | None = None
    seven_day_opus: PlanUsageBucket | None = None
    seven_day_sonnet: PlanUsageBucket | None = None
    fetched_at: float = 0.0


_cache: PlanUsageSnapshot | None = None
_cache_negative_until: float = 0.0


def _read_oauth_token() -> str | None:
    """Lê o accessToken do `~/.claude/.credentials.json`. Retorna None
    se o arquivo não existe, está malformado, ou não tem token."""
    path = Path.home() / ".claude" / ".credentials.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    return token if isinstance(token, str) and token else None


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_bucket(raw) -> PlanUsageBucket | None:
    if not isinstance(raw, dict):
        return None
    util = raw.get("utilization")
    if util is None:
        # Algumas tier-types podem usar `percentage_used` — tolerante.
        util = raw.get("percentage_used") or raw.get("percent")
    try:
        pct = float(util) if util is not None else 0.0
    except (TypeError, ValueError):
        pct = 0.0
    # Heurística: se a API devolver fração 0..1 em vez de 0..100, expande.
    if 0.0 < pct <= 1.0:
        pct *= 100.0
    return PlanUsageBucket(
        utilization_pct=max(0.0, min(pct, 999.0)),
        resets_at=_parse_iso(raw.get("resets_at")),
    )


def fetch_plan_usage(force: bool = False) -> PlanUsageSnapshot | None:
    """Devolve snapshot do `/api/oauth/usage` com cache de 60s.
    Retorna None se token ausente, request falha, ou rate-limited. UI
    deve cair pro cálculo USD-baseado nesse caso."""
    global _cache, _cache_negative_until
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache.fetched_at) < CACHE_TTL_SECONDS:
        return _cache
    # Cache negativo: depois de uma falha (rate limit/token expirado),
    # não retentar por um tempo — evita martelar a API a cada refresh
    # do painel (que roda a cada poucos segundos).
    if not force and now < _cache_negative_until:
        return _cache  # devolve o cache antigo se ainda existir (pode ser None)

    token = _read_oauth_token()
    if not token:
        _cache_negative_until = now + CACHE_TTL_SECONDS
        return _cache

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-cli (claude-workspaces)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        log.debug("falha em /api/oauth/usage: %s", exc)
        _cache_negative_until = now + CACHE_TTL_SECONDS
        return _cache

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        _cache_negative_until = now + CACHE_TTL_SECONDS
        return _cache

    if not isinstance(payload, dict) or "error" in payload:
        log.debug("/api/oauth/usage devolveu erro: %s", payload)
        _cache_negative_until = now + CACHE_TTL_SECONDS
        return _cache

    snap = PlanUsageSnapshot(
        five_hour=_parse_bucket(payload.get("five_hour")),
        seven_day=_parse_bucket(payload.get("seven_day")),
        seven_day_opus=_parse_bucket(payload.get("seven_day_opus")),
        seven_day_sonnet=_parse_bucket(payload.get("seven_day_sonnet")),
        fetched_at=now,
    )
    _cache = snap
    _cache_negative_until = 0.0
    return snap
