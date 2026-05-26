"""Helpers para a skill /notificar-discord montar e enviar o resumo da sessão.

A lógica que antes vivia inline no snippet bash da skill foi movida pra cá pra
ganhar testes (a skill é markdown, não roda em CI) e evitar que uma quebra só
apareça em runtime. A skill agora importa estas funções e fica com um snippet
curto.

Funções puras (sem rede): resolução do transcript da sessão, agregação de
métricas de uso, split do corpo respeitando o limite do embed e montagem de
título que preserva o marcador `(parte i/n)`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Limite real da `description` de um embed do Discord é 4096; deixamos folga.
EMBED_BODY_LIMIT = 3900
# Limite real do `title` de um embed.
EMBED_TITLE_LIMIT = 256


def encode_project_dir(cwd: Path | str) -> str:
    """Replica o esquema do Claude Code pra nomear a pasta de transcripts:
    o cwd absoluto vira `-home-user-proj` (cada `/` -> `-`, com `-` inicial).
    """
    p = str(Path(cwd)).strip("/")
    return "-" + p.replace("/", "-")


def projects_root(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude" / "projects"


def resolve_transcript(
    cwd: Path | str,
    *,
    session_id: str | None = None,
    env: dict | None = None,
    home: Path | None = None,
) -> Path | None:
    """Acha o .jsonl da sessão atual, em ordem de confiabilidade:

    1. `session_id` explícito (arg) → `<dir>/<id>.jsonl`.
    2. `CLAUDE_SESSION_ID` no ambiente → idem (útil quando o Claude Code
       expõe o id; hoje não expõe, mas fica à prova de futuro).
    3. fallback: o `.jsonl` modificado mais recentemente na pasta do projeto
       — é o que está sendo escrito pela sessão viva. Pode pegar a errada se
       houver duas sessões ativas no mesmo projeto no mesmo instante.

    Retorna None se a pasta não existe ou não há transcript (degrada em
    silêncio — métricas viram bloco vazio, sem quebrar a notificação).
    """
    env = env if env is not None else os.environ
    d = projects_root(home) / encode_project_dir(cwd)
    if not d.is_dir():
        return None
    sid = session_id or env.get("CLAUDE_SESSION_ID") or env.get("CLAUDE_TRANSCRIPT_SESSION_ID")
    if sid:
        cand = d / f"{sid}.jsonl"
        if cand.is_file():
            return cand
        # id informado mas arquivo não existe: cai pro fallback abaixo.
    files = list(d.glob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


@dataclass
class SessionMetrics:
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    models: tuple[str, ...] = ()
    duration_min: int | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def compute_metrics(transcript: Path | None) -> SessionMetrics | None:
    """Agrega `usage` das mensagens do assistente no transcript JSONL.

    Retorna None se não há transcript utilizável. Linhas malformadas são
    ignoradas (transcript pode estar sendo escrito concorrentemente).
    """
    if transcript is None or not transcript.is_file():
        return None
    inp = out = cc = cr = turns = 0
    models: set[str] = set()
    ts: list[str] = []
    for line in transcript.read_text("utf-8", "replace").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        m = o.get("message") or {}
        u = m.get("usage")
        if u:
            turns += 1
            inp += u.get("input_tokens", 0) or 0
            out += u.get("output_tokens", 0) or 0
            cc += u.get("cache_creation_input_tokens", 0) or 0
            cr += u.get("cache_read_input_tokens", 0) or 0
            if m.get("model"):
                models.add(m["model"])
        if o.get("timestamp"):
            ts.append(o["timestamp"])
    dur = None
    if len(ts) >= 2:
        try:
            a = dt.datetime.fromisoformat(ts[0].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(ts[-1].replace("Z", "+00:00"))
            dur = int((b - a).total_seconds() // 60)
        except Exception:
            dur = None
    return SessionMetrics(
        turns=turns, input_tokens=inp, output_tokens=out,
        cache_read=cr, cache_creation=cc,
        models=tuple(sorted(models)), duration_min=dur,
    )


def format_metrics(m: SessionMetrics | None) -> str:
    """Linha '📊 Sessão' pra anexar no corpo. String vazia se não há métricas."""
    if m is None or m.turns == 0:
        return ""
    dur = f" · ⏱ {m.duration_min} min" if m.duration_min is not None else ""
    models = ", ".join(m.models) or "?"
    return (
        f"\n\n📊 Sessão: {m.turns} turnos · {m.total_tokens:,} tokens "
        f"(↑{m.input_tokens:,} ↓{m.output_tokens:,}) · "
        f"cache {m.cache_read:,} lidos/{m.cache_creation:,} criados{dur} · {models}"
    )


def split_body(text: str, limit: int = EMBED_BODY_LIMIT) -> list[str]:
    """Quebra o corpo em pedaços <= limit, preferindo cortar em quebras de
    linha. Uma linha sozinha maior que o limite é cortada na marra."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) + 1 > limit:
            if buf:
                parts.append(buf)
            buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        parts.append(buf)
    return parts


def make_title(base: str, i: int, n: int, limit: int = EMBED_TITLE_LIMIT) -> str:
    """Título da parte i de n. Quando há múltiplas partes, reserva espaço pro
    sufixo ' (parte i/n)' truncando a BASE — assim o marcador nunca é comido
    por um título longo."""
    if n <= 1:
        return base[:limit]
    suffix = f" (parte {i}/{n})"
    room = max(0, limit - len(suffix))
    return base[:room] + suffix


__all__ = [
    "EMBED_BODY_LIMIT",
    "EMBED_TITLE_LIMIT",
    "SessionMetrics",
    "compute_metrics",
    "encode_project_dir",
    "format_metrics",
    "make_title",
    "projects_root",
    "resolve_transcript",
    "split_body",
]
