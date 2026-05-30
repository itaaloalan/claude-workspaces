"""Utilidades de texto puras — sem dependência de Qt.

Extraídas de terminal_child_widget para permitir testes unitários sem
inicializar widgets.
"""

import re

# Strip patterns que o statusline do Claude/OpenCode joga e poluem a sidebar.
# Aplicado em TerminalChildWidget._compose_state_text via _strip_noise.
_NOISE_PATTERNS = [
    re.compile(r"Context\s*[·:]?\s*[▒░▓█▏▎▍▌▋▊▉|\-_=]+\s*\d+\s*%", re.IGNORECASE),
    re.compile(r"\bContext\s+\d+\s*%", re.IGNORECASE),
    re.compile(r"[▒░▓█▏▎▍▌▋▊▉]+\s*\d+\s*%"),
    # OpenCode pode renderizar uma barra visual sem percentual — dominava
    # a sidebar e empurrava branch/modelo.
    re.compile(r"[·\s]*[█▉▊▋▌▍▎▏▒░▓■▪]+(?:[·\s]*[█▉▊▋▌▍▎▏▒░▓■▪]+){2,}"),
]


def _strip_noise(text: str) -> str:
    """Remove segmentos visualmente poluentes (progress bars do statusline)
    sem mexer no resto da última ação reportada."""
    if not text:
        return ""
    out = text
    for pat in _NOISE_PATTERNS:
        out = pat.sub("", out)
    # Limpa separadores '·' que sobraram pendurados.
    out = re.sub(r"\s*·\s*·\s*", " · ", out)
    out = out.strip(" ·\t")
    return out


def normalize_needle(text: str) -> str:
    """Normaliza o termo de busca digitado na sidebar (trim + lower)."""
    return (text or "").strip().lower()


def matches_filter(needle: str, haystack: str) -> bool:
    """Predicado puro do filtro da sidebar: item visível?

    `needle` deve vir já normalizado (ver `normalize_needle`). Termo vazio
    casa tudo (lista inteira visível). Caso contrário, substring case-folded.
    """
    if not needle:
        return True
    return needle in (haystack or "").lower()
