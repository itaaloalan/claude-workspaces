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


def strip_ansi(text: str) -> str:
    """Remove sequências ANSI/escape do texto (cores, cursor, OSC)."""
    return _ANSI_RE.sub("", text)


def _strip_ansi(text: str) -> str:  # alias interno (compat)
    return strip_ansi(text)


_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+", re.IGNORECASE)
_PR_NUM_RE = re.compile(r"/pull/(\d+)")
_MR_URL_RE = re.compile(r"https://[^\s]+/merge_requests/\d+", re.IGNORECASE)
_MR_NUM_RE = re.compile(r"/merge_requests/(\d+)")


def detect_pr_url(text: str) -> str | None:
    """Detecta URL de PR (GitHub) ou MR (GitLab) no texto.
    Aceita ANSI ainda presente — faz strip internamente."""
    if not text:
        return None
    cleaned = _strip_ansi(text)
    matches = list(_PR_URL_RE.finditer(cleaned))
    if matches:
        return matches[-1].group(0).rstrip(".,;)")
    matches = list(_MR_URL_RE.finditer(cleaned))
    if matches:
        return matches[-1].group(0).rstrip(".,;)")
    return None


def pr_number_from_url(url: str) -> str | None:
    """Extrai o número do PR/MR de uma URL do GitHub ou GitLab."""
    m = _PR_NUM_RE.search(url) or _MR_NUM_RE.search(url)
    return m.group(1) if m else None


def pr_label_from_url(url: str) -> str:
    """Retorna label formatado: 'MR #N' para GitLab, 'PR #N' para GitHub."""
    num = pr_number_from_url(url)
    prefix = "MR" if _MR_NUM_RE.search(url) else "PR"
    return f"{prefix} #{num}" if num else prefix


_URL_PORT_RE = re.compile(r"(://[^/:\s]+):(\d{1,5})")


def url_port(url: str) -> int:
    """Porta explícita de uma URL (0 quando ausente/inválida)."""
    m = _URL_PORT_RE.search(url or "")
    if not m:
        return 0
    try:
        return int(m.group(2))
    except ValueError:
        return 0


def swap_url_port(url: str, port: int) -> str:
    """Troca a porta explícita `:NNNN` da URL por `port`, preservando
    host/path/query. URL sem porta explícita ou `port <= 0` → intacta.

    Usado pelo open-browser do runner: a URL da config carrega o PATH
    certo mas pode ter a porta hardcoded — a porta REAL (detectada no
    log ou alocada) entra no lugar."""
    if port <= 0 or not url:
        return url
    return _URL_PORT_RE.sub(lambda m: f"{m.group(1)}:{port}", url, count=1)
