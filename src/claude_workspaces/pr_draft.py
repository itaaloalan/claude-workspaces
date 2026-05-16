"""Constrói o draft de Pull Request (título + body Markdown) a partir do
log de commits desde o base branch. Puro — separa coleta (subprocess git)
de formatação (`build_draft`) pra ser fácil de testar."""

import logging
import os
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Separadores ASCII pouco usados — evitam colisão com conteúdo de commit
SEP_RECORD = "\x1e"
SEP_FIELD = "\x1f"

TIMEOUT_S = 10


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str = ""


@dataclass
class PRDraft:
    title: str
    body: str


def _run_log(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", "log", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("git log falhou: %s", e)
        return -1, ""
    return r.returncode, r.stdout


def list_commits_since_base(folder: str, base: str) -> list[Commit]:
    """Commits acima de `base` em HEAD, mais antigo primeiro. Tenta `base`
    local primeiro; cai pra `origin/<base>` se faltar."""
    fmt = f"%H{SEP_FIELD}%s{SEP_FIELD}%b{SEP_RECORD}"
    for ref in (base, f"origin/{base}"):
        rc, out = _run_log([f"{ref}..HEAD", f"--format={fmt}", "--reverse"], folder)
        if rc == 0:
            commits = _parse_log(out)
            if commits:
                return commits
    return []


def _parse_log(raw: str) -> list[Commit]:
    commits: list[Commit] = []
    for chunk in raw.split(SEP_RECORD):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split(SEP_FIELD, 2)
        if len(parts) < 2:
            continue
        sha = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""
        if not sha or not subject:
            continue
        commits.append(Commit(sha=sha, subject=subject, body=body))
    return commits


def build_draft(commits: list[Commit], fallback_title: str = "") -> PRDraft:
    """Monta título + body Markdown:
    - 0 commits: stub
    - 1 commit: título = subject, body usa o body do commit como resumo
    - N commits: título = commit mais recente, body lista todos os subjects
    """
    if not commits:
        title = fallback_title or "(sem commits acima do base)"
        body = (
            "## Resumo\n"
            "_Sem commits acima do base branch._\n\n"
            "## Test plan\n"
            "- [ ] \n"
        )
        return PRDraft(title=title, body=body)

    if len(commits) == 1:
        c = commits[0]
        resumo = c.body.strip() or c.subject
        body = (
            "## Resumo\n"
            f"{resumo}\n\n"
            "## Test plan\n"
            "- [ ] \n"
        )
        return PRDraft(title=c.subject, body=body)

    # Múltiplos: título do mais recente (último na lista, que está reversed)
    title = commits[-1].subject
    lines = ["## Resumo", ""]
    for c in commits:
        lines.append(f"- {c.subject}")
    lines.extend(["", "## Test plan", "- [ ] ", ""])
    return PRDraft(title=title, body="\n".join(lines))


def build_draft_for_folder(folder: str, base: str, fallback_title: str = "") -> PRDraft:
    """Atalho: list_commits_since_base + build_draft."""
    commits = list_commits_since_base(folder, base)
    return build_draft(commits, fallback_title=fallback_title)
