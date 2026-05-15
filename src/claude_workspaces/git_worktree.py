"""Wrapper sobre `git worktree` pra isolar um console do Claude numa
nova branch sem interferir com a working tree principal.

Convenção: worktrees criados via app moram em
  <parent>/<reponame>.claude/<safe-branch-name>/

assim ficam visíveis (não dentro do .git) mas fora do tree principal.
"""

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path


log = logging.getLogger(__name__)

TIMEOUT_S = 60


def _run(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 255, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def suggest_branch_name() -> str:
    return f"claude/{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def safe_dir_name(branch: str) -> str:
    """Substitui caracteres problemáticos no nome da branch pra
    transformar em diretório válido."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", branch)


def worktree_base(repo_path: str) -> Path:
    repo = Path(repo_path)
    return repo.parent / (repo.name + ".claude")


def worktree_path_for(repo_path: str, branch: str) -> Path:
    return worktree_base(repo_path) / safe_dir_name(branch)


def add_worktree(
    repo_path: str, branch: str, base_branch: str | None = None
) -> tuple[bool, str, Path]:
    """Cria worktree em <parent>/<repo>.claude/<safe-branch>.
    Retorna (ok, mensagem_de_erro, path)."""
    dest = worktree_path_for(repo_path, branch)
    if dest.exists():
        return False, f"path já existe: {dest}", dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "worktree", "add", "-b", branch, str(dest)]
    if base_branch:
        args.append(base_branch)
    rc, out = _run(args, repo_path)
    if rc != 0:
        return False, out, dest
    return True, "", dest


def remove_worktree(worktree_path: str) -> tuple[bool, str]:
    """Remove o worktree. Pede ao git pra fazer cleanup do registro
    interno + remove o diretório."""
    # Descobre o repo principal
    rc, out = _run(["git", "rev-parse", "--show-toplevel"], worktree_path)
    if rc != 0:
        return False, f"não foi possível resolver o repo: {out}"
    main_repo = out.strip()
    if Path(main_repo).resolve() == Path(worktree_path).resolve():
        return False, "esse path é o repo principal, não um worktree"
    rc, out = _run(
        ["git", "worktree", "remove", "--force", worktree_path], main_repo
    )
    return rc == 0, out


def list_worktrees(repo_path: str) -> list[dict]:
    rc, out = _run(["git", "worktree", "list", "--porcelain"], repo_path)
    if rc != 0:
        return []
    result: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                result.append(current)
                current = {}
            continue
        if " " in line:
            k, v = line.split(" ", 1)
            current[k] = v
        else:
            current[line] = "1"
    if current:
        result.append(current)
    return result
