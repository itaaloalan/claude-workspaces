"""Detecta URLs/portas no stdout de runners web pra abrir o browser.

Olha um buffer recente da saída e tenta extrair `http(s)://host:port/path`
ou compor a partir de `port: NNNN` / `listening on NNNN`. Retorna a URL
mais provável ou None.
"""

from __future__ import annotations

import re

# URL completa: prioriza localhost/127.0.0.1 (dev local).
_URL_RE = re.compile(
    r"https?://"
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|[a-zA-Z0-9.-]+)"
    r"(?::\d{2,5})?"
    r"(?:/[^\s'\"`<>]*)?",
    re.IGNORECASE,
)

# Padrões só de porta (rails, django, etc): "Listening on 3000", "port: 8080".
_PORT_RE = re.compile(
    r"(?:listening on(?: port)?|port[:\s=]+|server started on(?: port)?|"
    r"running on(?: port)?|started server on(?: port)?)\s*[:=]?\s*"
    r"(?:0\.0\.0\.0:|127\.0\.0\.1:|localhost:)?(\d{2,5})\b",
    re.IGNORECASE,
)

# 0.0.0.0/host vira localhost no browser.
_REWRITE_HOST = {"0.0.0.0": "localhost", "[::1]": "localhost", "[::]": "localhost"}


def detect_url(text: str) -> str | None:
    """Procura a URL mais provável no texto. Aceita ANSI já strip-ado."""
    if not text:
        return None
    cleaned = _strip_ansi(text)

    # 1) URL crua. Prefere a última matching (servers costumam logar
    #    a URL final depois de warnings).
    matches = _URL_RE.findall(cleaned)
    if matches:
        # findall com grupos não-capturantes devolve só a string inteira
        url = _normalize(matches[-1])
        if url:
            return url

    # 2) Só porta. Compõe http://localhost:<port>/.
    port_match = None
    for m in _PORT_RE.finditer(cleaned):
        port_match = m
    if port_match:
        return f"http://localhost:{port_match.group(1)}/"

    return None


def _normalize(url: str) -> str | None:
    url = url.strip().rstrip(".,;)")
    if not url:
        return None
    for raw, repl in _REWRITE_HOST.items():
        url = url.replace(f"//{raw}", f"//{repl}")
    return url


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
