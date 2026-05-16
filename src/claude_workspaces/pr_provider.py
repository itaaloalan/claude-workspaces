"""Detecta provider GitHub do remote `origin` e calcula estado da branch
atual contra um base branch.

Mantido enxuto: só GitHub por enquanto (GitLab/Bitbucket viram depois).
Helpers de URL são puros (parse_github_remote) — fáceis de testar; o resto
toca subprocess `git` com timeout curto."""

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Aceita owner/repo com letras, dígitos, ., _, -. Repo sem ".git" no path
# também é válido (gh clone gera URL "limpa").
GITHUB_HTTPS_RE = re.compile(
    r"^https?://(?:[^@/]+@)?github\.com/([^/]+)/([^/\s]+?)(?:\.git)?/?$"
)
GITHUB_SSH_RE = re.compile(
    r"^(?:ssh://)?git@github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$"
)

TIMEOUT_S = 5


@dataclass(frozen=True)
class GithubRemote:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class BranchState:
    current: str = ""
    base: str = ""
    has_upstream: bool = False
    ahead: int = 0
    behind: int = 0
    dirty: bool = False
    error: str = ""


def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return -1, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def parse_github_remote(url: str) -> GithubRemote | None:
    """Aceita HTTPS, SSH (`git@`), com ou sem `.git`. None se não casar."""
    url = (url or "").strip()
    if not url:
        return None
    m = GITHUB_HTTPS_RE.match(url) or GITHUB_SSH_RE.match(url)
    if not m:
        return None
    owner = m.group(1).strip()
    repo = m.group(2).strip()
    if not owner or not repo:
        return None
    return GithubRemote(owner=owner, repo=repo)


def get_remote_url(folder: str, remote: str = "origin") -> str:
    rc, out = _run_git(["remote", "get-url", remote], folder)
    return out if rc == 0 else ""


def detect_github(folder: str) -> GithubRemote | None:
    return parse_github_remote(get_remote_url(folder))


def detect_base_branch(folder: str) -> str:
    """Tenta na ordem: origin/HEAD (config local) → main → master → 'main'."""
    rc, out = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], folder)
    if rc == 0 and out.startswith("refs/remotes/origin/"):
        return out.removeprefix("refs/remotes/origin/")
    rc, _ = _run_git(["rev-parse", "--verify", "main"], folder)
    if rc == 0:
        return "main"
    rc, _ = _run_git(["rev-parse", "--verify", "master"], folder)
    if rc == 0:
        return "master"
    return "main"


def current_branch(folder: str) -> str:
    rc, out = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], folder)
    if rc != 0 or out == "HEAD":
        return ""
    return out


def has_upstream(folder: str) -> bool:
    rc, _ = _run_git(["rev-parse", "--abbrev-ref", "@{u}"], folder)
    return rc == 0


def ahead_behind(folder: str, base: str) -> tuple[int, int]:
    """Devolve (ahead, behind) de HEAD contra `base`. Tenta `base` local
    primeiro; se faltar, tenta `origin/<base>`. (0,0) se nada bate."""
    for ref in (base, f"origin/{base}"):
        rc, out = _run_git(
            ["rev-list", "--left-right", "--count", f"{ref}...HEAD"],
            folder,
        )
        if rc == 0 and out:
            parts = out.split()
            if len(parts) == 2:
                try:
                    behind, ahead = int(parts[0]), int(parts[1])
                    return ahead, behind
                except ValueError:
                    continue
    return 0, 0


def is_dirty(folder: str) -> bool:
    rc, out = _run_git(["status", "--porcelain"], folder)
    return rc == 0 and bool(out.strip())


def branch_state(folder: str, base: str | None = None) -> BranchState:
    """Snapshot do estado do branch atual: current/base/upstream/ahead/behind/dirty."""
    if not folder or not Path(folder).is_dir():
        return BranchState(error="diretório inexistente")
    if base is None:
        base = detect_base_branch(folder)
    cur = current_branch(folder)
    if not cur:
        return BranchState(base=base, error="não é repo git ou HEAD detached")
    ahead, behind = ahead_behind(folder, base)
    return BranchState(
        current=cur,
        base=base,
        has_upstream=has_upstream(folder),
        ahead=ahead,
        behind=behind,
        dirty=is_dirty(folder),
    )
