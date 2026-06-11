"""Agrega uso de tokens por workspace lendo as sessões do Claude Code.

Cada mensagem assistant tem `message.usage` com input_tokens, output_tokens,
cache_creation_input_tokens, cache_read_input_tokens, e `message.model`.
Custos aproximados por modelo (USD por 1M tokens). Atualize se Anthropic
mudar preços.
"""

import json
import logging
import os
import stat as stat_mod
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
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


def aggregate_usage_opencode(since: datetime | None = None) -> dict[str, UsageStats]:
    """Aggregate token usage from opencode SQLite database."""
    import sqlite3
    db_path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
    if not db_path.exists():
        return {}
    out: dict[str, UsageStats] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        since_ts = int(since.timestamp() * 1000) if since else 0
        cursor.execute(
            """SELECT s.directory, s.model, s.tokens_input, s.tokens_output,
                      s.tokens_reasoning, s.tokens_cache_read, s.tokens_cache_write,
                      s.cost, s.time_updated
               FROM session s
               WHERE s.time_updated >= ?
               ORDER BY s.time_updated ASC""",
            (since_ts,),
        )
        for row in cursor.fetchall():
            cwd = row["directory"]
            if cwd not in out:
                out[cwd] = UsageStats()
            s = out[cwd]
            s.input_tokens += row["tokens_input"] or 0
            s.output_tokens += row["tokens_output"] or 0
            s.cache_read_tokens += row["tokens_cache_read"] or 0
            s.cache_creation_tokens += row["tokens_cache_write"] or 0
            s.cost_usd += row["cost"] or 0.0
            s.sessions += 1
            updated = datetime.fromtimestamp(row["time_updated"] / 1000, tz=UTC)
            if s.last_used is None or updated > s.last_used:
                s.last_used = updated
            model_raw = row["model"]
            if model_raw:
                try:
                    m = json.loads(model_raw)
                    model_id = m.get("id", str(model_raw))
                except (json.JSONDecodeError, TypeError):
                    model_id = str(model_raw)
                total = (
                    (row["tokens_input"] or 0)
                    + (row["tokens_output"] or 0)
                    + (row["tokens_cache_read"] or 0)
                    + (row["tokens_cache_write"] or 0)
                )
                s.by_model[model_id] = s.by_model.get(model_id, 0) + total
                s.last_model = model_id
        conn.close()
    except (sqlite3.Error, OSError) as e:
        log.warning("Falha ao ler telemetria opencode: %s", e)
    return out


def aggregate_usage_by_workspace(
    since: datetime | None = None,
    backend: str = "claude",
) -> dict[str, UsageStats]:
    if backend == "opencode":
        return aggregate_usage_opencode(since)
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


def _accumulate_session_line(stats: UsageStats, raw: bytes) -> None:
    """Acumula uma linha de JSONL de sessão em `stats`. Todos os campos
    são append-monotônicos (somas, max de ts, overwrite do "último"), então
    aplicar só as linhas novas equivale a re-parsear o arquivo inteiro."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    if msg.get("type") != "assistant":
        return
    ts = _parse_timestamp(msg.get("timestamp", ""))
    inner = msg.get("message") or {}
    if not isinstance(inner, dict):
        return
    usage = inner.get("usage") or {}
    if not isinstance(usage, dict):
        return
    model = inner.get("model") or "?"
    i = int(usage.get("input_tokens") or 0)
    o = int(usage.get("output_tokens") or 0)
    cc = int(usage.get("cache_creation_input_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    if i + o + cc + cr <= 0 and model == "?":
        return
    stats.input_tokens += i
    stats.output_tokens += o
    stats.cache_creation_tokens += cc
    stats.cache_read_tokens += cr
    stats.cost_usd += _model_cost(model, usage)
    stats.by_model[model] = stats.by_model.get(model, 0) + (i + o + cc + cr)
    if model and model != "?":
        stats.last_model = model
    # Tokens "em contexto" desta virada: input + cache (lido + criado).
    # Sobrescreve a cada iteração — fica com o valor da última mensagem
    # assistant do JSONL.
    stats.last_context_tokens = i + cc + cr
    if ts and (stats.last_used is None or ts > stats.last_used):
        stats.last_used = ts


@dataclass
class _SessionCacheEntry:
    size: int
    mtime_ns: int
    ino: int
    offset: int  # byte logo após a última linha completa já parseada
    tail: bytes  # últimos bytes antes do offset — detecta rewrite in-place
    stats: UsageStats
    last_access: float


_TAIL_CHECK_BYTES = 64


# Cache incremental de usage_for_session: o tick de 5s da MainWindow chama
# isso pra cada console visível, e re-parsear um JSONL de dezenas de MB a
# cada tick travava a UI. A invalidação é por estado do arquivo (size +
# mtime_ns + inode), NUNCA por TTL — qualquer append/truncamento é detectado
# na chamada seguinte, então o valor devolvido reflete sempre o disco atual.
_session_cache: dict[str, _SessionCacheEntry] = {}
_session_cache_lock = threading.Lock()
_SESSION_CACHE_MAX = 64


def _copy_stats(stats: UsageStats) -> UsageStats:
    # by_model é mutável e compartilhado — nunca vaza o dict do cache.
    return replace(stats, by_model=dict(stats.by_model))


def usage_for_session(jsonl_path: Path) -> UsageStats:
    """Lê um único JSONL e devolve UsageStats agregado dessa sessão.
    `last_model` reflete o modelo da mensagem assistant mais recente —
    útil quando o usuário usa /model no meio da sessão pra trocar.

    Incremental: arquivo inalterado → cache; cresceu (mesmo inode) → parseia
    só os bytes novos; encolheu/trocou de inode/mudou sem crescer → re-parse
    total. Linha parcial (append em andamento) fica pro próximo tick."""
    key = str(jsonl_path)
    try:
        st = os.stat(jsonl_path)
    except OSError:
        with _session_cache_lock:
            _session_cache.pop(key, None)
        return UsageStats()
    if not stat_mod.S_ISREG(st.st_mode):
        return UsageStats()

    now = time.monotonic()
    sig = (st.st_size, st.st_mtime_ns, st.st_ino)
    with _session_cache_lock:
        entry = _session_cache.get(key)
        if entry is not None and sig == (entry.size, entry.mtime_ns, entry.ino):
            entry.last_access = now
            return _copy_stats(entry.stats)

    # Append no mesmo arquivo → retoma do offset salvo; qualquer outra
    # mudança (truncamento, rewrite, rotação) → começa do zero. O tail
    # confirma que o conteúdo já parseado não foi reescrito in-place.
    incremental = (
        entry is not None and st.st_ino == entry.ino and st.st_size > entry.size
    )
    offset = 0
    stats = UsageStats()
    try:
        with open(jsonl_path, "rb") as fp:
            if incremental and entry is not None:
                fp.seek(max(0, entry.offset - len(entry.tail)))
                if fp.read(len(entry.tail)) == entry.tail:
                    stats = _copy_stats(entry.stats)
                    stats.sessions = 0  # re-setado no fim, como no full
                    offset = entry.offset
                else:
                    fp.seek(0)  # prefixo mudou: rewrite disfarçado de append
            tail = entry.tail if offset else b""
            for raw in fp:
                if not raw.endswith(b"\n"):
                    break  # linha parcial — consumida quando completar
                offset += len(raw)
                tail = (tail + raw)[-_TAIL_CHECK_BYTES:]
                _accumulate_session_line(stats, raw)
        stats.sessions = 1
    except OSError:
        log.debug("falha ao ler %s", jsonl_path, exc_info=True)
        return stats

    with _session_cache_lock:
        _session_cache[key] = _SessionCacheEntry(
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            ino=st.st_ino,
            offset=offset,
            tail=tail,
            stats=stats,
            last_access=now,
        )
        if len(_session_cache) > _SESSION_CACHE_MAX:
            oldest = sorted(
                _session_cache.items(), key=lambda kv: kv[1].last_access
            )
            for k, _ in oldest[: len(_session_cache) - _SESSION_CACHE_MAX]:
                _session_cache.pop(k, None)
    return _copy_stats(stats)


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


# Cache por arquivo das linhas assistant relevantes pro plan usage. Chave de
# validade = (size, mtime_ns, inode): arquivo inalterado não é re-parseado;
# QUALQUER mudança re-lê o arquivo na mesma chamada (sem TTL → sem dado velho).
# rows: lista de (ts, model, usage) com ts válido e tokens > 0 — exatamente o
# conjunto que as janelas 5h e semanal filtram. Não mutar as rows devolvidas.
_rows_cache: dict[str, tuple[tuple[int, int, int], list[tuple]]] = {}
_rows_cache_lock = threading.Lock()


def _assistant_rows(jsonl: Path) -> list[tuple]:
    try:
        st = os.stat(jsonl)
    except OSError:
        return []
    sig = (st.st_size, st.st_mtime_ns, st.st_ino)
    key = str(jsonl)
    with _rows_cache_lock:
        hit = _rows_cache.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
    rows: list[tuple] = []
    try:
        with open(jsonl, "rb") as fp:
            for raw in fp:
                try:
                    msg = json.loads(raw)
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
                rows.append((ts, inner.get("model") or "?", usage))
    except OSError:
        return rows
    with _rows_cache_lock:
        _rows_cache[key] = (sig, rows)
    return rows


def _prune_rows_cache(keep: set[str]) -> None:
    """Descarta entradas de arquivos que saíram da janela de varredura —
    sem isso o cache cresceria com cada sessão que já foi recente um dia."""
    with _rows_cache_lock:
        for k in [k for k in _rows_cache if k not in keep]:
            _rows_cache.pop(k, None)


def weekly_plan_usage(window_days: int = 7) -> WeeklyPlanUsage:
    """Soma custos de assistant messages nos últimos `window_days` dias,
    separando Sonnet do total."""
    return local_plan_usage(window_days=window_days)[1]


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
    """Replica `Plan usage limits → Current session` do claude.ai."""
    return local_plan_usage(window_seconds=window_seconds)[0]


def local_plan_usage(
    window_seconds: int = 5 * 3600, window_days: int = 7
) -> tuple[PlanUsageWindow, WeeklyPlanUsage]:
    """Calcula as duas janelas locais (sessão 5h + semanal) numa única
    varredura de ~/.claude/projects — o cutoff de mtime da janela 5h é
    subconjunto do semanal, então não há por que varrer duas vezes.

    Janela 5h: Anthropic abre uma "sessão" na 1a mensagem após um gap
    >=5h e fecha quando passa 5h do início. O que conta é o uso DESSA
    sessão atual — não uma janela rolante. Algoritmo:
      1. Coleta as mensagens dos JSONL recentes (mtime na última janela
         2x pra cobrir borda).
      2. Ordena por ts e detecta o `session_start` corrente: 1a mensagem
         tal que `session_start + window` > now.
      3. Soma só do `session_start` em diante.
    `first_ts` no retorno é o session_start (não o cutoff da janela),
    então `first_ts + 5h` = reset real exibido pela UI."""
    recent = PlanUsageWindow()
    weekly = WeeklyPlanUsage()
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return recent, weekly
    now = datetime.now(UTC)
    weekly_cutoff = now - timedelta(days=window_days)
    weekly_cutoff_epoch = weekly_cutoff.timestamp()
    # Pré-filtro da janela 5h: arquivos modificados na última 2*janela —
    # cobre o caso de a sessão atual ter começado pouco antes do cutoff.
    recent_mtime_cutoff = (now - timedelta(seconds=window_seconds * 2)).timestamp()
    try:
        projects = list(base.iterdir())
    except OSError:
        return recent, weekly

    msgs: list[tuple] = []  # (ts, model, usage) dos arquivos recentes
    seen: set[str] = set()
    for proj in projects:
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            if mtime < weekly_cutoff_epoch:
                continue
            rows = _assistant_rows(jsonl)
            seen.add(str(jsonl))
            is_recent_file = mtime >= recent_mtime_cutoff
            for ts, model, usage in rows:
                if ts >= weekly_cutoff:
                    i = int(usage.get("input_tokens") or 0)
                    o = int(usage.get("output_tokens") or 0)
                    cc = int(usage.get("cache_creation_input_tokens") or 0)
                    cr = int(usage.get("cache_read_input_tokens") or 0)
                    cost = _model_cost(model, usage)
                    weekly.all_cost_usd += cost
                    weekly.total_tokens += i + o + cc + cr
                    if "sonnet" in model.lower():
                        weekly.sonnet_cost_usd += cost
                if is_recent_file:
                    msgs.append((ts, model, usage))
    _prune_rows_cache(seen)

    if not msgs:
        return recent, weekly
    msgs.sort(key=lambda x: x[0])
    window = timedelta(seconds=window_seconds)
    # Walk: cada vez que aparece uma msg fora da janela do session_start
    # atual, ela vira o novo session_start.
    session_start: datetime | None = None
    for ts, _m, _u in msgs:
        if session_start is None or ts >= session_start + window:
            session_start = ts
    if session_start is None or session_start + window <= now:
        return recent, weekly  # sessão 5h expirou — nada a mostrar

    for ts, model, usage in msgs:
        if ts < session_start:
            continue
        i = int(usage.get("input_tokens") or 0)
        o = int(usage.get("output_tokens") or 0)
        cc = int(usage.get("cache_creation_input_tokens") or 0)
        cr = int(usage.get("cache_read_input_tokens") or 0)
        recent.cost_usd += _model_cost(model, usage)
        recent.total_tokens += i + o + cc + cr
        if recent.latest_ts is None or ts > recent.latest_ts:
            recent.latest_ts = ts
    recent.first_ts = session_start
    return recent, weekly
