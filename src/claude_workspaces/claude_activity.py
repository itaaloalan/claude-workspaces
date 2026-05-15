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


ANSI_CSI_RE = re.compile(r"\x1b\[[\d;?<>!]*[A-Za-z@`]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI_OTHER_RE = re.compile(r"\x1b[78NDEcMH=>\(\)*+]\S?")  # single-char e charset escapes
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")  # mantém \n e \t
CR_RE = re.compile(r"\r(?!\n)")

# Marcadores do prompt idle do Claude Code (auto-mode footer)
IDLE_MARKERS = (
    "auto mode on",
    "shift+tab to cycle",
    "esc to interrupt",
    "press shift+tab",
    "automodeon",  # ANSI-stripped sem espaços (acontece com algumas builds do Claude)
    "shifttab",
    "esctointerrupt",
)


@dataclass
class Activity:
    status: str
    is_working: bool


def strip_ansi(text: str) -> str:
    text = ANSI_OSC_RE.sub("", text)
    text = ANSI_CSI_RE.sub("", text)
    text = ANSI_OTHER_RE.sub("", text)
    text = CR_RE.sub("\n", text)
    text = CTRL_RE.sub("", text)
    return text


def _is_meaningful(line: str) -> bool:
    """Filtra linhas só com box-drawing/separadores/espaços."""
    return any(c.isalnum() for c in line)


def _is_idle_marker(line: str) -> bool:
    low = line.lower().replace(" ", "")
    return any(m.replace(" ", "") in low for m in IDLE_MARKERS)


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
    last_is_idle = _is_idle_marker(last)
    looks_prompt = last in (">", "$", "%", "#") or last.endswith(" $")

    # Pra mostrar como "última ação": prefere a última linha que NÃO
    # seja o footer/auto-mode/prompt. Sem isso, o status mostraria sempre
    # 'auto mode on (shift+tab to cycle) · ...' depois que Claude termina.
    display_line = last
    if last_is_idle or looks_prompt:
        for line in reversed(lines[:-1]):
            if _is_idle_marker(line):
                continue
            if line in (">", "$", "%", "#") or line.endswith(" $"):
                continue
            display_line = line
            break

    # Limpa prefix "* " usado pelo Claude (ex: "* Stewing…")
    display = display_line
    if display.startswith("* "):
        display = display[2:].strip()
    if len(display) > 90:
        display = display[:89] + "…"

    recent = last_output_age < 2.5
    is_working = recent and not last_is_idle and not looks_prompt

    return Activity(status=display, is_working=is_working)
