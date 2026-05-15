"""Agrega uso de tokens por workspace lendo as sessões do Claude Code.

Cada mensagem assistant tem `message.usage` com input_tokens, output_tokens,
cache_creation_input_tokens, cache_read_input_tokens, e `message.model`.
Custos aproximados por modelo (USD por 1M tokens). Atualize se Anthropic
mudar preços.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


# Preços por 1M tokens (USD). Aproximados — atualizar conforme Anthropic
# muda. Se modelo desconhecido, conta tokens mas custo fica 0.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 15.0, "output": 75.0,
        "cache_creation": 18.75, "cache_read": 1.50,
    },
    "claude-opus-4-7[1m]": {
        "input": 30.0, "output": 150.0,
        "cache_creation": 37.50, "cache_read": 3.00,
    },
    "claude-sonnet-4-6": {
        "input": 3.0, "output": 15.0,
        "cache_creation": 3.75, "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 0.80, "output": 4.0,
        "cache_creation": 1.0, "cache_read": 0.08,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.0,
        "cache_creation": 1.0, "cache_read": 0.08,
    },
}


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    sessions: int = 0
    last_used: datetime | None = None
    by_model: dict[str, int] = field(default_factory=dict)  # model → total tokens

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _project_path_from_encoded(name: str) -> str:
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name


def _model_cost(model: str, u: dict) -> float:
    prices = PRICING.get(model)
    if not prices:
        return 0.0

    def per_m(key: str, count: int) -> float:
        return prices[key] * count / 1_000_000

    return (
        per_m("input", int(u.get("input_tokens") or 0))
        + per_m("output", int(u.get("output_tokens") or 0))
        + per_m("cache_creation", int(u.get("cache_creation_input_tokens") or 0))
        + per_m("cache_read", int(u.get("cache_read_input_tokens") or 0))
    )


def aggregate_usage_by_workspace(
    since: datetime | None = None,
) -> dict[str, UsageStats]:
    """Devolve {cwd: UsageStats}. since limita por timestamp da mensagem.
    Cwd vem do campo 'cwd' dentro da mensagem — confiável, vs reverter
    o encoding do nome do diretório (lossy quando o path tem hífen)."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return {}
    out: dict[str, UsageStats] = {}
    seen_sessions_by_cwd: dict[str, set[Path]] = {}
    try:
        projects = list(base.iterdir())
    except OSError:
        return {}
    for proj in projects:
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                with jsonl.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "assistant":
                            continue
                        cwd = msg.get("cwd") or ""
                        if not cwd:
                            continue
                        ts = _parse_timestamp(msg.get("timestamp", ""))
                        if since and ts and ts < since:
                            continue
                        inner = msg.get("message") or {}
                        if not isinstance(inner, dict):
                            continue
                        usage = inner.get("usage") or {}
                        if not isinstance(usage, dict):
                            continue
                        model = inner.get("model") or "?"
                        i = int(usage.get("input_tokens") or 0)
                        o = int(usage.get("output_tokens") or 0)
                        cc = int(usage.get("cache_creation_input_tokens") or 0)
                        cr = int(usage.get("cache_read_input_tokens") or 0)
                        if i + o + cc + cr <= 0:
                            continue
                        stats = out.get(cwd)
                        if stats is None:
                            stats = UsageStats()
                            out[cwd] = stats
                        stats.input_tokens += i
                        stats.output_tokens += o
                        stats.cache_creation_tokens += cc
                        stats.cache_read_tokens += cr
                        stats.cost_usd += _model_cost(model, usage)
                        stats.by_model[model] = (
                            stats.by_model.get(model, 0) + (i + o + cc + cr)
                        )
                        if ts and (stats.last_used is None or ts > stats.last_used):
                            stats.last_used = ts
                        seen_sessions_by_cwd.setdefault(cwd, set()).add(jsonl)
            except OSError:
                continue
    for cwd, files in seen_sessions_by_cwd.items():
        out[cwd].sessions = len(files)
    return out


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
