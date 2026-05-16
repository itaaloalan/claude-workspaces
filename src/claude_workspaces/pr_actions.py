"""Runners pra ações de PR no GitHub via `gh` CLI.

Por que `gh` e não a API direta:
- Zero config: auth já tá no `gh auth status` do usuário.
- Sem token nos settings (evita armadilha de secret em arquivo).
- Custo: precisa do `gh` instalado — `pr_available()` reporta isso.
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

PUSH_TIMEOUT_S = 60
PR_TIMEOUT_S = 60
VIEW_TIMEOUT_S = 15


@dataclass
class PRResult:
    ok: bool
    url: str = ""
    error: str = ""


@dataclass
class ExistingPR:
    """PR já existente pra branch (state ∈ {"OPEN","CLOSED","MERGED"})."""
    url: str
    state: str
    number: int


def gh_available() -> bool:
    """True se o binário `gh` está no PATH."""
    return shutil.which("gh") is not None


def push_with_upstream(
    folder: str, branch: str, remote: str = "origin"
) -> tuple[bool, str]:
    """`git push -u <remote> <branch>` — necessário antes do `gh pr create`
    se a branch não tem upstream. Roda em foreground com timeout."""
    try:
        r = subprocess.run(
            ["git", "push", "-u", remote, branch],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=PUSH_TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def create_pr_github(
    folder: str,
    title: str,
    body: str,
    base: str,
    draft: bool = False,
) -> PRResult:
    """`gh pr create` — devolve PRResult com URL capturada do output."""
    if not gh_available():
        return PRResult(
            ok=False,
            error="`gh` CLI não está instalado. Instale com `paru -S github-cli`.",
        )
    args = ["gh", "pr", "create", "--base", base, "--title", title, "--body", body]
    if draft:
        args.append("--draft")
    try:
        r = subprocess.run(
            args,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=PR_TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return PRResult(ok=False, error=str(e))
    output = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return PRResult(ok=False, error=output)
    url = _extract_pr_url(output)
    return PRResult(ok=True, url=url or output)


def _extract_pr_url(output: str) -> str:
    """gh pr create imprime mensagens + URL em alguma linha. Pega a última
    que começa com https://github.com/."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("https://github.com/"):
            return line
    return ""


def find_existing_pr(folder: str, branch: str) -> ExistingPR | None:
    """Procura PR existente associado à `branch`. Devolve o mais relevante
    (gh prioriza OPEN). None se não há nenhum ou se gh não tá disponível.

    `gh pr view <branch> --json url,state,number` sai com:
    - rc=0 + JSON quando existe
    - rc!=0 com mensagem "no pull requests found" quando não existe
    Não diferenciamos erro de "sem PR" — caller decide se quer reportar.
    """
    if not gh_available():
        return None
    try:
        r = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "url,state,number"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=VIEW_TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("gh pr view falhou: %s", e)
        return None
    if r.returncode != 0:
        # Mensagem comum: "no pull requests found for branch <name>"
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        log.warning("gh pr view devolveu JSON inválido: %r", r.stdout[:200])
        return None
    url = (data.get("url") or "").strip()
    state = (data.get("state") or "").strip().upper()
    number = data.get("number") or 0
    if not url:
        return None
    return ExistingPR(url=url, state=state, number=int(number))
