"""Descoberta do plano (plan mode) de uma sessão Claude.

Quando o Claude Code entra em plan mode ele grava o plano em
`~/.claude/plans/<slug>.md` e o transcript JSONL da sessão referencia
esse path (system-reminder do plan mode + resultado do Write). A última
ocorrência no transcript é o plano atual da sessão.

O scan é tail-first: lê o transcript do FIM em blocos e para no primeiro
bloco com match — transcripts podem ter centenas de MB (lição da
SkillsPanel/0.83.1) e o plano quase sempre é referenciado perto do fim.
Cache por (path, mtime, size) evita re-scan quando o transcript não mudou.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Path absoluto do plano dentro do JSONL. Escapes JSON (\\/ ou \\")
# não acontecem nos paths gravados pelo Claude Code, então um match
# direto na linha crua é suficiente — sem parsear JSON linha a linha.
_PLAN_PATH_RE = re.compile(rb"/[^\"'\\\s]*?\.claude/plans/[^\"'\\\s]+?\.md")

# Blocos de 256 KB: grande o bastante pra achar o plano em 1-2 reads
# na maioria dos transcripts, pequeno o bastante pra não pesar.
_CHUNK = 256 * 1024

# Cache: transcript path -> ((mtime_ns, size), PlanInfo | None)
_cache: dict[Path, tuple[tuple[int, int], "PlanInfo | None"]] = {}


@dataclass(frozen=True)
class PlanInfo:
    """Plano descoberto — frozen pra ser seguro entre threads."""

    path: Path
    title: str
    mtime: float

    def read_markdown(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Falha lendo plano %s: %s", self.path, e)
            return f"_(erro lendo plano: {e})_"


def _title_from_plan(path: Path) -> str:
    """Primeiro heading do .md; fallback: slug do filename humanizado."""
    try:
        with path.open(encoding="utf-8") as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("#"):
                    return stripped.lstrip("#").strip() or path.stem
    except OSError:
        pass
    return path.stem.replace("-", " ").strip() or path.name


def _scan_tail_for_plan_path(transcript: Path, size: int) -> Path | None:
    """Última referência a `.claude/plans/*.md` no transcript, lendo do fim.

    Mantém um overlap entre blocos pra não perder um path cortado na
    fronteira (paths têm < 4 KB com folga).
    """
    overlap = 4096
    with transcript.open("rb") as f:
        pos = size
        carry = b""
        while pos > 0:
            start = max(0, pos - _CHUNK)
            f.seek(start)
            block = f.read(pos - start) + carry
            matches = _PLAN_PATH_RE.findall(block)
            if matches:
                # Último match do bloco mais próximo do fim do arquivo.
                try:
                    return Path(matches[-1].decode("utf-8"))
                except UnicodeDecodeError:
                    return None
            carry = block[:overlap]
            pos = start
    return None


def find_session_plan(transcript: Path | None) -> PlanInfo | None:
    """Plano atual da sessão cujo transcript é `transcript`.

    Retorna None se não há transcript, nenhum plano foi referenciado,
    ou o arquivo do plano não existe mais. Pode rodar fora da UI thread.
    """
    if transcript is None:
        return None
    try:
        st = os.stat(transcript)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    cached = _cache.get(transcript)
    if cached is not None and cached[0] == key:
        info = cached[1]
        # Plano pode ter sido reescrito sem o transcript mudar (raro) —
        # revalida existência + mtime do .md, que é stat barato.
        if info is None:
            return None
        try:
            plan_st = os.stat(info.path)
        except OSError:
            return None
        if plan_st.st_mtime != info.mtime:
            info = PlanInfo(
                path=info.path,
                title=_title_from_plan(info.path),
                mtime=plan_st.st_mtime,
            )
            _cache[transcript] = (key, info)
        return info

    plan_path: Path | None = None
    try:
        plan_path = _scan_tail_for_plan_path(transcript, st.st_size)
    except OSError as e:
        log.warning("Falha escaneando transcript %s: %s", transcript, e)

    info: PlanInfo | None = None
    if plan_path is not None:
        try:
            plan_st = os.stat(plan_path)
            info = PlanInfo(
                path=plan_path,
                title=_title_from_plan(plan_path),
                mtime=plan_st.st_mtime,
            )
        except OSError:
            info = None  # plano referenciado mas já apagado
    _cache[transcript] = (key, info)
    return info
