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
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Marcador literal do path do plano dentro do JSONL. Escapes JSON (\\/ ou
# \\") não acontecem nos paths gravados pelo Claude Code, então busca
# direta no bloco cru é suficiente — sem parsear JSON linha a linha.
# NUNCA trocar por regex com quantificador antes do marcador: a versão
# regex (`/[^\"'\\\s]*?\.claude/plans/...`) sofria backtracking
# catastrófico em blobs base64 de imagens coladas (6s+ por bloco de
# 256 KB, GIL preso, UI congelada).
_PLAN_MARKER = b".claude/plans/"
# Bytes que terminam um path dentro do JSON cru (aspas, backslash e
# whitespace — o mesmo conjunto de `[^\"'\\\s]`).
_PATH_BOUNDARY = frozenset(b"\"'\\ \t\n\r\x0b\x0c")

# Blocos de 256 KB: grande o bastante pra achar o plano em 1-2 reads
# na maioria dos transcripts, pequeno o bastante pra não pesar.
_CHUNK = 256 * 1024

# Cache: transcript path -> (mtime_ns, size escaneado, PlanInfo | None).
# Transcripts são append-only, então quando o arquivo só cresce basta
# escanear o tail novo — sem match novo, a última referência antiga
# continua sendo o plano atual.
_cache: dict[Path, tuple[int, int, "PlanInfo | None"]] = {}


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


def _extract_plan_path(block: bytes) -> bytes | None:
    """Última ocorrência válida de `/...\\.claude/plans/<nome>.md` no bloco.

    Busca literal do marcador (rfind, custo linear) + expansão manual
    até as fronteiras do path — equivale ao antigo regex
    `/[^\"'\\\\\\s]*?\\.claude/plans/[^\"'\\\\\\s]+?\\.md` sem o
    backtracking.
    """
    end = len(block)
    while True:
        idx = block.rfind(_PLAN_MARKER, 0, end)
        if idx < 0:
            return None
        # Pra trás: começo do run de bytes válidos; o path começa no
        # primeiro '/' dentro dele (paths são absolutos).
        run = idx
        while run > 0 and block[run - 1] not in _PATH_BOUNDARY:
            run -= 1
        start = block.find(b"/", run, idx + 1)
        # Pra frente: primeiro ".md" (com >= 1 char de nome) dentro do
        # run de bytes válidos após o marcador.
        name = idx + len(_PLAN_MARKER)
        stop = name
        while stop < len(block) and block[stop] not in _PATH_BOUNDARY:
            stop += 1
        md = block.find(b".md", name + 1, stop)
        if start >= 0 and md >= 0:
            return block[start : md + 3]
        end = idx  # ocorrência inválida — tenta a anterior no bloco


def _scan_tail_for_plan_path(
    transcript: Path, size: int, stop_at: int = 0
) -> Path | None:
    """Última referência a `.claude/plans/*.md` no transcript, lendo do fim.

    Mantém um overlap entre blocos pra não perder um path cortado na
    fronteira (paths têm < 4 KB com folga). `stop_at` limita o scan ao
    tail ainda não visto (scan incremental): a leitura para nesse offset
    menos o overlap, cobrindo um path cortado na fronteira antiga.
    """
    overlap = 4096
    floor = max(0, stop_at - overlap)
    with transcript.open("rb") as f:
        pos = size
        carry = b""
        while pos > floor:
            start = max(floor, pos - _CHUNK)
            f.seek(start)
            block = f.read(pos - start) + carry
            found = _extract_plan_path(block)
            if found is not None:
                try:
                    return Path(found.decode("utf-8"))
                except UnicodeDecodeError:
                    return None
            carry = block[:overlap]
            pos = start
    return None


def _revalidate(info: PlanInfo) -> PlanInfo | None:
    """Plano pode ter sido reescrito/apagado sem o transcript mudar —
    revalida existência + mtime do .md, que é stat barato."""
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
    return info


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
    cached = _cache.get(transcript)
    if (
        cached is not None
        and cached[0] == st.st_mtime_ns
        and cached[1] == st.st_size
    ):
        info = _revalidate(cached[2]) if cached[2] is not None else None
        _cache[transcript] = (st.st_mtime_ns, st.st_size, info)
        return info

    # Transcript é append-only: se só cresceu, escaneia apenas o tail
    # novo; sem match novo, a última referência anterior segue valendo.
    stop_at = 0
    prev_info: PlanInfo | None = None
    if cached is not None and cached[1] <= st.st_size:
        stop_at = cached[1]
        prev_info = cached[2]

    plan_path: Path | None = None
    try:
        plan_path = _scan_tail_for_plan_path(transcript, st.st_size, stop_at)
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
    elif prev_info is not None:
        info = _revalidate(prev_info)
    _cache[transcript] = (st.st_mtime_ns, st.st_size, info)
    return info
