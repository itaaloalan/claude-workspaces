"""Agrega uso de tokens por workspace lendo as sessões do Claude Code.

Cada mensagem assistant tem `message.usage` com input_tokens, output_tokens,
cache_creation_input_tokens, cache_read_input_tokens, e `message.model`.
Custos aproximados por modelo (USD por 1M tokens). Atualize se Anthropic
mudar preços.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    last_model: str = ""  # modelo da última mensagem assistant — reflete /model dentro da sessão
    # Tokens "em contexto" da última mensagem assistant (input + cache create +
    # cache read). Representa o tamanho real da janela de contexto na última
    # virada — é isso que o /context do Claude Code mostra como percentual.
    last_context_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


def context_window_for_model(model: str) -> int:
    """Limite da janela de contexto em tokens. Modelos com sufixo `[1m]`
    têm 1M; o resto da família Claude 4.x usa 200K."""
    if not model:
        return 200_000
    if "[1m]" in model:
        return 1_000_000
    return 200_000


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


def usage_for_session(jsonl_path: Path) -> UsageStats:
    """Lê um único JSONL e devolve UsageStats agregado dessa sessão.
    `last_model` reflete o modelo da mensagem assistant mais recente —
    útil quando o usuário usa /model no meio da sessão pra trocar."""
    stats = UsageStats()
    if not jsonl_path.is_file():
        return stats
    try:
        with jsonl_path.open(encoding="utf-8") as fp:
            for line in fp:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "assistant":
                    continue
                ts = _parse_timestamp(msg.get("timestamp", ""))
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
                if i + o + cc + cr <= 0 and model == "?":
                    continue
                stats.input_tokens += i
                stats.output_tokens += o
                stats.cache_creation_tokens += cc
                stats.cache_read_tokens += cr
                stats.cost_usd += _model_cost(model, usage)
                stats.by_model[model] = (
                    stats.by_model.get(model, 0) + (i + o + cc + cr)
                )
                if model and model != "?":
                    stats.last_model = model
                # Tokens "em contexto" desta virada: input + cache (lido +
                # criado). Sobrescreve a cada iteração — fica com o valor
                # da última mensagem assistant do JSONL.
                stats.last_context_tokens = i + cc + cr
                if ts and (stats.last_used is None or ts > stats.last_used):
                    stats.last_used = ts
        stats.sessions = 1
    except OSError:
        log.debug("falha ao ler %s", jsonl_path, exc_info=True)
    return stats


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


@dataclass
class WeeklyPlanUsage:
    """Uso agregado da janela semanal (replica `Weekly limits` do claude.ai).
    Anthropic mostra duas faixas: `All models` (tudo somado) e `Sonnet only`
    (só sonnet). Aqui devolvemos custos separados pra cada uma. Reset é
    fixo num horário semanal (não calculamos aqui — UI deriva)."""
    all_cost_usd: float = 0.0
    sonnet_cost_usd: float = 0.0
    total_tokens: int = 0


def weekly_plan_usage(window_days: int = 7) -> WeeklyPlanUsage:
    """Soma custos de assistant messages nos últimos `window_days` dias,
    separando Sonnet do total. Reaproveita o mesmo varrer de JSONLs do
    plan_usage 5h, mas em janela maior."""
    out = WeeklyPlanUsage()
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    cutoff_epoch = cutoff.timestamp()
    try:
        projects = list(base.iterdir())
    except OSError:
        return out
    for proj in projects:
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                if jsonl.stat().st_mtime < cutoff_epoch:
                    continue
            except OSError:
                continue
            try:
                with jsonl.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "assistant":
                            continue
                        ts = _parse_timestamp(msg.get("timestamp", ""))
                        if ts is None or ts < cutoff:
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
                        cost = _model_cost(model, usage)
                        out.all_cost_usd += cost
                        out.total_tokens += i + o + cc + cr
                        if "sonnet" in model.lower():
                            out.sonnet_cost_usd += cost
            except OSError:
                continue
    return out


@dataclass
class PlanUsageWindow:
    """Uso agregado da janela rolante de 5h (replica `Plan usage limits →
    Current session` do claude.ai). Anthropic limita por uma janela de 5h
    desde a primeira mensagem da "sessão"; aqui aproximamos como janela
    rolante (close enough pra mostrar o %)."""
    cost_usd: float = 0.0
    total_tokens: int = 0
    first_ts: datetime | None = None  # 1a msg dentro da janela (proxy de "session start")
    latest_ts: datetime | None = None  # msg mais recente dentro da janela


def recent_plan_usage(window_seconds: int = 5 * 3600) -> PlanUsageWindow:
    """Replica `Plan usage limits → Current session` do claude.ai.

    Anthropic abre uma "sessão" de 5h na 1a mensagem após um gap >=5h e
    fecha quando passa 5h do início. O que conta é o uso DESSA sessão
    atual — não uma janela rolante. Algoritmo:
      1. Coleta todas as mensagens dos JSONL recentes (mtime na última
         janela 2x pra cobrir borda).
      2. Ordena por ts e detecta o `session_start` corrente: 1a mensagem
         tal que `session_start + window` > now.
      3. Soma só do `session_start` em diante.
    `first_ts` no retorno é o session_start (não o cutoff da janela),
    então `first_ts + 5h` = reset real exibido pela UI.
    """
    out = PlanUsageWindow()
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return out
    now = datetime.now(timezone.utc)
    # Pré-filtra arquivos modificados na última 2*janela — cobre o caso
    # de a sessão atual ter começado pouco antes do cutoff rolante.
    mtime_cutoff = (now - timedelta(seconds=window_seconds * 2)).timestamp()
    try:
        projects = list(base.iterdir())
    except OSError:
        return out

    msgs: list[tuple[datetime, str, dict]] = []  # (ts, model, usage)
    for proj in projects:
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                if jsonl.stat().st_mtime < mtime_cutoff:
                    continue
            except OSError:
                continue
            try:
                with jsonl.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "assistant":
                            continue
                        ts = _parse_timestamp(msg.get("timestamp", ""))
                        if ts is None:
                            continue
                        inner = msg.get("message") or {}
                        if not isinstance(inner, dict):
                            continue
                        usage = inner.get("usage") or {}
                        if not isinstance(usage, dict):
                            continue
                        i = int(usage.get("input_tokens") or 0)
                        o = int(usage.get("output_tokens") or 0)
                        cc = int(usage.get("cache_creation_input_tokens") or 0)
                        cr = int(usage.get("cache_read_input_tokens") or 0)
                        if i + o + cc + cr <= 0:
                            continue
                        msgs.append((ts, inner.get("model") or "?", usage))
            except OSError:
                continue

    if not msgs:
        return out
    msgs.sort(key=lambda x: x[0])
    window = timedelta(seconds=window_seconds)
    # Walk: cada vez que aparece uma msg fora da janela do session_start
    # atual, ela vira o novo session_start.
    session_start: datetime | None = None
    for ts, _m, _u in msgs:
        if session_start is None or ts >= session_start + window:
            session_start = ts
    if session_start is None or session_start + window <= now:
        return out  # sessão expirou — nada a mostrar

    for ts, model, usage in msgs:
        if ts < session_start:
            continue
        i = int(usage.get("input_tokens") or 0)
        o = int(usage.get("output_tokens") or 0)
        cc = int(usage.get("cache_creation_input_tokens") or 0)
        cr = int(usage.get("cache_read_input_tokens") or 0)
        out.cost_usd += _model_cost(model, usage)
        out.total_tokens += i + o + cc + cr
        if out.latest_ts is None or ts > out.latest_ts:
            out.latest_ts = ts
    out.first_ts = session_start
    return out
