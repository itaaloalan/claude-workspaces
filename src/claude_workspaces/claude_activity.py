"""Parser leve do output do Claude Code (ou de qualquer shell) pra
extrair o "que está acontecendo agora" como uma linha curta + flag
trabalhando/aguardando.

Heurística:
- Strip de ANSI/carriage-returns
- Pega a última linha "interessante" (com pelo menos um alfanumérico)
- Decide working baseado em (a) tempo desde último output do pty e
  (b) presença de marcadores idle conhecidos
"""

import re
from dataclasses import dataclass


ANSI_RE = re.compile(r"\x1b\[[\d;?]*[a-zA-Z]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*\x07")  # OSC commands ending in BEL
CR_RE = re.compile(r"\r(?!\n)")

# Marcadores do prompt idle do Claude Code (auto-mode footer)
IDLE_MARKERS = (
    "auto mode on",
    "shift+tab to cycle",
    "esc to interrupt",
    "press shift+tab",
)


@dataclass
class Activity:
    status: str
    is_working: bool


def strip_ansi(text: str) -> str:
    text = ANSI_OSC_RE.sub("", text)
    text = ANSI_RE.sub("", text)
    text = CR_RE.sub("\n", text)
    return text


def _is_meaningful(line: str) -> bool:
    """Filtra linhas só com box-drawing/separadores/espaços."""
    return any(c.isalnum() for c in line)


def parse_status(buffer_bytes: bytes, last_output_age: float = 0.0) -> Activity:
    """Recebe os últimos N bytes do pty + idade do último write (em s)."""
    try:
        text = buffer_bytes.decode("utf-8", errors="replace")
    except Exception:
        return Activity(status="", is_working=False)
    text = strip_ansi(text)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines = [l for l in lines if _is_meaningful(l)]
    if not lines:
        return Activity(status="", is_working=False)

    last = lines[-1]
    last_lower = last.lower()

    # Limpa prefix "* " usado pelo Claude (ex: "* Stewing…")
    display = last.lstrip("* ").strip() if last.startswith("* ") else last
    if len(display) > 90:
        display = display[:89] + "…"

    looks_idle = any(m in last_lower for m in IDLE_MARKERS)
    looks_prompt = last in (">", "$", "%", "#") or last.endswith(" $")

    # Output recente (< 2.5s) + não parece linha de prompt/auto-mode → working
    recent = last_output_age < 2.5
    is_working = recent and not looks_idle and not looks_prompt

    return Activity(status=display, is_working=is_working)
