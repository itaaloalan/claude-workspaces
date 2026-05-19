"""Parser leve do output do Claude Code (ou de qualquer shell) pra
extrair o "que está acontecendo agora" como uma linha curta + flag
trabalhando/aguardando.

Heurística:
- Strip de ANSI/carriage-returns
- Pega a última linha "interessante" (com pelo menos um alfanumérico)
- Detecção POSITIVA de working: procura o indicador do Claude
  ("* Word… · X tokens · esc to interrupt") nas últimas linhas.
  Sem esse indicador, NÃO marca como working — mesmo que tenha tido
  output recente (footer/prompt repintando, cursor piscando etc.).
- Fallback genérico (shell qualquer): output recente + sem prompt → working.
- Detecção POSITIVA de awaiting-decision: procura padrões de prompt de
  permissão do Claude ("Do you want to proceed?" + opções numeradas com
  setas "❯"). Sem esse indicador, NÃO marca como awaiting — Claude no
  prompt principal depois de terminar um turno é "ocioso", não "aguardando".
"""

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

ANSI_CSI_RE = re.compile(r"\x1b\[[\d;?<>!]*[A-Za-z@`]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI_OTHER_RE = re.compile(r"\x1b[78NDEcMH=>\(\)*+]\S?")  # single-char e charset escapes
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")  # mantém \n e \t
CR_RE = re.compile(r"\r(?!\n)")

# Marcadores do prompt idle do Claude Code (auto-mode footer e variantes).
# Comparação é feita após normalização alfa-numérica (sem espaços, hífens,
# pontuação), então "auto-mode on" casa com "auto mode on".
#
# IMPORTANTE: "esc to interrupt" também aparece em estados de IDLE (footer)
# mas é o marker dominante quando Claude está trabalhando, então é
# tratado especialmente: WORKING_RE captura a linha de trabalho inteira.
IDLE_MARKERS = (
    "auto mode on",
    "auto-mode on",
    "auto update",
    "shift+tab to cycle",
    "esc to interrupt",
    "press shift+tab",
    "for shortcuts",         # "? for shortcuts"
    "accept edits on",
    "bypass permissions",
    "plan mode on",
)

# Subconjunto usado pra detectar "Claude pronto pra receber input" —
# exclui "esc to interrupt" porque essa string aparece DENTRO da linha de
# working ("* Word... · X tokens · esc to interrupt"), então casar por
# ela leva a falso positivo de "pronto" enquanto Claude trabalha.
PROMPT_READY_MARKERS = (
    "auto mode on",
    "auto-mode on",
    "shift+tab to cycle",
    "press shift+tab",
    "for shortcuts",
    "accept edits on",
    "bypass permissions",
    "plan mode on",
)

# Indicador positivo de trabalho no Claude TUI:
#   "* Stewing… (5s · ↓ 0 tokens · esc to interrupt)"
#   "* Cultivating thoughts… (2s · 1.3k tokens · esc to interrupt)"
# Casa pelo prefixo "* <word>" + "tokens" na mesma linha.
WORKING_RE = re.compile(r"\*\s+\w+.*?tokens", re.IGNORECASE)

# Indicadores positivos de "Claude está pedindo decisão" (permission prompt,
# escolha de tool, confirmação). Cobertura:
#   1. Permission tool-prompt clássico:
#        "Do you want to proceed?"
#        "Do you want to make this edit to Foo.java?"
#        "❯ 1. Yes / 2. No / ..."
#      → casa quando "Do you want" aparece junto com "❯ N." no tail.
#   2. Picker interativo (skill picker, plan mode, /commands, escolhas
#      customizadas tipo "Qual direção?"). O footer canônico é
#        "Enter to select · ↑/↓ to navigate · Esc to cancel"
#      Esse footer só aparece quando o picker está aberto bloqueando input,
#      então sozinho já basta como sinal de awaiting-decision.
DECISION_QUESTION_RE = re.compile(r"\bdo you want\b", re.IGNORECASE)
DECISION_CHOICE_RE = re.compile(r"❯\s*\d+\.")
INTERACTIVE_FOOTER_RE = re.compile(r"enter to select", re.IGNORECASE)

# Versões normalizadas (só [a-z0-9]) usadas como fallback quando o Claude TUI
# emite o texto com cursor positioning absoluto entre palavras — strip_ansi
# remove os escapes mas não reinsere os espaços, então "Enter to select"
# vira "Entertoselect" e a regex acima não casa. Why: dump real do buffer
# mostrou a linha "Entertoselect·↑/↓tonavigate·Esctocancel", o que travou
# a detecção e fez sessões com picker aberto aparecerem como "Ocioso".
_INTERACTIVE_FOOTER_NORM = "entertoselect"
_DECISION_QUESTION_NORM = "doyouwant"

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

PROMPT_TAILS = (">", "$", "%", "#")


@dataclass
class Activity:
    status: str
    is_working: bool
    needs_decision: bool = False


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


def _normalize(text: str) -> str:
    """Reduz a [a-z0-9] pra casar markers ignorando espaços, hífens, pontos
    e caracteres unicode decorativos."""
    return _NON_ALNUM_RE.sub("", text.lower())


def _is_idle_marker(line: str) -> bool:
    norm = _normalize(line)
    if not norm:
        return False
    return any(_normalize(m) in norm for m in IDLE_MARKERS)


def _last_index(lines: list[str], predicate) -> int:
    """Índice da última linha que casa o predicado, ou -1."""
    for i in range(len(lines) - 1, -1, -1):
        if predicate(lines[i]):
            return i
    return -1


def _has_working_marker(lines: list[str]) -> bool:
    """Procura o indicador ativo do Claude (* Word… tokens) nas últimas
    linhas. Janela curta (6) pra não casar conteúdo velho na buffer."""
    for line in lines[-6:]:
        if WORKING_RE.search(line):
            return True
    return False


def _has_decision_prompt(lines: list[str]) -> bool:
    """True se as últimas linhas contêm um permission prompt ou picker
    interativo do Claude.

    Janela maior (12) porque o "Do you want to..." pode ficar algumas
    linhas acima da seta "❯ 1." de escolha. O footer de picker
    ("Enter to select…") sozinho já basta — ele só aparece com input
    bloqueado."""
    tail = lines[-12:]
    tail_norm = [_normalize(ln) for ln in tail]
    if any(_INTERACTIVE_FOOTER_NORM in n for n in tail_norm):
        return True
    has_question = any(_DECISION_QUESTION_NORM in n for n in tail_norm)
    has_choice = any(DECISION_CHOICE_RE.search(ln) for ln in tail)
    return has_question and has_choice


def _looks_like_prompt(line: str) -> bool:
    return line in PROMPT_TAILS or line.endswith(" $")


def _is_prompt_ready_marker(line: str) -> bool:
    norm = _normalize(line)
    if not norm:
        return False
    return any(_normalize(m) in norm for m in PROMPT_READY_MARKERS)


def has_idle_marker(buffer_bytes: bytes) -> bool:
    """True se o buffer contém um prompt-ready marker do Claude perto do
    fim das últimas linhas E não há working marker mais recente. Usado pra
    detectar quando o TUI está pronto pra receber input. Decodifica +
    strip_ansi por conta, então pode receber o buffer cru do pty."""
    try:
        text = buffer_bytes.decode("utf-8", errors="replace")
    except Exception:
        log.exception("has_idle_marker: decode falhou (não deveria com errors=replace)")
        return False
    text = strip_ansi(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if _is_meaningful(ln)]
    if not lines:
        return False
    ready_idx = _last_index(lines, _is_prompt_ready_marker)
    if ready_idx < 0 or ready_idx < len(lines) - 5:
        return False
    # Working marker em qualquer linha igual ou mais recente vence
    working_idx = _last_index(lines, lambda ln: bool(WORKING_RE.search(ln)))
    if working_idx >= ready_idx:
        return False
    return True


def parse_status(buffer_bytes: bytes, last_output_age: float = 0.0) -> Activity:
    """Recebe os últimos N bytes do pty + idade do último write (em s)."""
    try:
        text = buffer_bytes.decode("utf-8", errors="replace")
    except Exception:
        log.exception("parse_status: decode falhou (não deveria com errors=replace)")
        return Activity(status="", is_working=False)
    text = strip_ansi(text)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if _is_meaningful(ln)]
    if not lines:
        return Activity(status="", is_working=False)

    last = lines[-1]
    last_is_idle = _is_idle_marker(last)
    looks_prompt = _looks_like_prompt(last)
    last_is_picker_footer = _INTERACTIVE_FOOTER_NORM in _normalize(last)

    # Posição da última ocorrência de cada marker. Quem aparece DEPOIS no
    # buffer ganha — assim Claude trabalhando seguido do footer cai pra
    # idle, e Claude começando a trabalhar (working marker novo) supera
    # um footer velho.
    idle_idx = _last_index(lines, _is_idle_marker)
    working_idx = _last_index(lines, lambda ln: bool(WORKING_RE.search(ln)))
    tail_has_idle = idle_idx >= 0 and idle_idx >= len(lines) - 5
    has_working = working_idx >= 0 and working_idx >= len(lines) - 6
    idle_is_more_recent = idle_idx > working_idx

    # Pra mostrar como "última ação": prefere a última linha que NÃO
    # seja footer/auto-mode/prompt/footer-de-picker. Sem isso, o status
    # mostraria sempre 'auto mode on (shift+tab to cycle) · ...' depois
    # que Claude termina, ou 'Enter to select · ↑/↓ to navigate' quando
    # um picker está aberto.
    display_line = last
    if last_is_idle or looks_prompt or last_is_picker_footer:
        for line in reversed(lines[:-1]):
            if _is_idle_marker(line):
                continue
            if _looks_like_prompt(line):
                continue
            if _INTERACTIVE_FOOTER_NORM in _normalize(line):
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

    # Detecção positiva: o marker "* Word… tokens · esc to interrupt" é
    # evidência de Claude trabalhando. Enquanto ele estiver visível nas
    # últimas linhas E nenhum idle marker mais recente tiver aparecido,
    # mantemos is_working=True mesmo sem output novo.
    #
    # Why: usar `recent` como tiebreaker aqui flipava o estado pra idle no
    # meio do trabalho (extended thinking, tool runs lentas, latência de
    # rede facilmente passam dos 2.5s sem cuspir nada no TUI). Cada flip
    # disparava inbox_alert → notificação "✅ Pronto" que aparecia e sumia
    # quando o próximo chunk reativava working. Quando Claude termina de
    # verdade, o footer idle aparece DEPOIS do working marker
    # (idle_is_more_recent), e a transição é detectada normalmente.
    if has_working and not (tail_has_idle and idle_is_more_recent):
        is_working = True
    elif tail_has_idle or looks_prompt:
        is_working = False
    else:
        # Fallback pra shells genéricos sem markers do Claude.
        is_working = recent and not looks_prompt

    # Decisão pendente só vale quando Claude NÃO está trabalhando — durante
    # working o buffer pode arrastar restos de prompt anterior.
    needs_decision = (not is_working) and _has_decision_prompt(lines)

    return Activity(
        status=display, is_working=is_working, needs_decision=needs_decision
    )
