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
#   1. Permission tool-prompt clássico (numbered):
#        "Do you want to proceed?"
#        "❯ 1. Yes / 2. No / ..."
#      → casa quando "Do you want" aparece junto com "❯ N." no tail.
#   2. Permission prompt moderno (yes/no sem número):
#        "❯ Yes" / "❯ No" / "❯ yes, don't ask again"
#        "Allow Claude to run bash?"
#      → casa quando ❯ precede yes/no/allow/deny OU há questão de "allow".
#   3. Picker interativo (skill picker, plan mode, /commands, etc).
#        "Enter to select · ↑/↓ to navigate · Esc to cancel"
#      Esse footer só aparece com input bloqueado → sozinho já basta.
DECISION_QUESTION_RE = re.compile(r"\bdo you want\b", re.IGNORECASE)
DECISION_ALLOW_RE = re.compile(r"\ballow\b.{0,60}\?", re.IGNORECASE)
DECISION_CHOICE_RE = re.compile(r"❯\s*\d+\.")
# Formato moderno sem número: "❯ Yes" / "❯ No" / "❯ yes, don't ask again"
DECISION_CHOICE_YN_RE = re.compile(r"❯\s*(?:yes|no|allow|deny|approve|reject)", re.IGNORECASE)
# ASCII > como seletor (algumas versões/terminais usam > em vez de ❯).
DECISION_CHOICE_ASCII_RE = re.compile(r"^>\s+(?:yes|no|allow|deny|approve|reject)", re.IGNORECASE)
INTERACTIVE_FOOTER_RE = re.compile(r"enter to select", re.IGNORECASE)

# Frases exclusivas do permission prompt — sozinhas identificam a tela,
# mesmo que o ❯ venha de cursor positioning e não apareça numa linha limpa.
_PERM_SPECIFIC_NORMS = ("dontaskagain", "allowonce", "allowalways", "denyandstop")

# Versões normalizadas (só [a-z0-9]) usadas como fallback quando o Claude TUI
# emite o texto com cursor positioning absoluto entre palavras — strip_ansi
# remove os escapes mas não reinsere os espaços, então "Enter to select"
# vira "Entertoselect" e a regex acima não casa.
_INTERACTIVE_FOOTER_NORM = "entertoselect"
# Frases de pergunta de decisão. "do you want" → permission prompt clássico;
# "would you like" → prompt do plan mode ("...ready to execute. Would you
# like to proceed?"). Ambas exigem uma escolha visível para virar decisão.
_DECISION_QUESTION_NORMS = ("doyouwant", "wouldyoulike")
_DECISION_ALLOW_NORM = "allow"

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

PROMPT_TAILS = (">", "$", "%", "#")


@dataclass
class Activity:
    status: str
    is_working: bool
    needs_decision: bool = False
    is_plan_mode: bool = False


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

    Janela maior (16) porque o "Do you want to..." / "Allow..." pode
    ficar algumas linhas acima da seta de escolha. O footer de picker
    ("Enter to select…") sozinho já basta — ele só aparece com input
    bloqueado. Formato moderno usa "❯ Yes/No" ou "> Yes/No" sem número."""
    tail = lines[-16:]
    tail_norm = [_normalize(ln) for ln in tail]
    full_tail_norm = "".join(tail_norm)
    # Footer do picker interativo — sozinho basta.
    if any(_INTERACTIVE_FOOTER_NORM in n for n in tail_norm):
        return True
    # Frases exclusivas do permission prompt (ex: "don't ask again",
    # "allow once") — únicas nesse contexto, dispensam presença de ❯.
    if any(p in full_tail_norm for p in _PERM_SPECIFIC_NORMS):
        return True
    # Formato moderno: "❯ Yes/No" (Unicode) ou "> Yes/No" (ASCII, \s* por
    # eventual cursor positioning que remove o espaço após strip).
    has_yn_choice = any(
        DECISION_CHOICE_YN_RE.search(ln) or DECISION_CHOICE_ASCII_RE.match(ln)
        for ln in tail
    )
    if has_yn_choice:
        return True
    # Formato clássico: "Do you want...?" / plan mode "Would you like...?"
    # + "❯ 1." numerado.
    has_question = any(
        any(q in n for q in _DECISION_QUESTION_NORMS) for n in tail_norm
    )
    has_numbered_choice = any(DECISION_CHOICE_RE.search(ln) for ln in tail)
    if has_question and has_numbered_choice:
        return True
    # "Allow Claude to X?" + qualquer seleção (❯ ou > ASCII).
    has_allow = any(DECISION_ALLOW_RE.search(ln) for ln in tail)
    has_any_choice = has_numbered_choice or has_yn_choice or any(
        "❯" in ln or bool(DECISION_CHOICE_ASCII_RE.match(ln)) for ln in tail
    )
    return has_allow and has_any_choice


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
    # Pré-computa decision prompt pra evitar chamada dupla e pra usar no fallback.
    has_decision = _has_decision_prompt(lines)

    if has_working and not (tail_has_idle and idle_is_more_recent):
        is_working = True
    elif tail_has_idle or looks_prompt:
        is_working = False
    else:
        # Fallback pra shells genéricos sem markers do Claude.
        # Se há decision prompt visível, definitivamente não está trabalhando —
        # sem isso, re-renders parciais do TUI (cursor/spinner, age < 2.5s)
        # disparam is_working=True, limpam o hold e derrubam o status pra Ocioso.
        is_working = recent and not looks_prompt and not has_decision

    # Decisão pendente só vale quando Claude NÃO está trabalhando — durante
    # working o buffer pode arrastar restos de prompt anterior.
    needs_decision = (not is_working) and has_decision

    # Plan mode: "plan mode on" visível nas últimas 5 linhas (footer idle).
    _PLAN_NORM = _normalize("plan mode on")
    plan_idx = _last_index(lines, lambda ln: _PLAN_NORM in _normalize(ln))
    is_plan_mode = plan_idx >= 0 and plan_idx >= len(lines) - 5

    return Activity(
        status=display,
        is_working=is_working,
        needs_decision=needs_decision,
        is_plan_mode=is_plan_mode,
    )
