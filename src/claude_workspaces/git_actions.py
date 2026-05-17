"""Ações git escritas que mutam o repo (pull/fetch/commit/stage).

Cada função roda em foreground via subprocess com timeout e devolve
(success: bool, output: str) — caller decide se mostra QMessageBox.
"""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

TIMEOUT_S = 60


def _run(args: list[str], cwd: str) -> tuple[bool, str]:
    if not Path(cwd).is_dir():
        return False, f"diretório inexistente: {cwd}"
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
        return False, str(e)
    output = (r.stdout + r.stderr).strip() or f"exit code {r.returncode}"
    return r.returncode == 0, output


def fetch(folder: str) -> tuple[bool, str]:
    return _run(["git", "fetch", "--prune"], folder)


def head_sha(folder: str) -> str:
    """SHA do HEAD; vazio se algo falhar.

    Não usa _run (tem timeout maior do que precisamos pra rev-parse) —
    rev-parse responde em < 5ms e a UI bloqueia esperando."""
    if not Path(folder).is_dir():
        return ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def pull_ff_only(folder: str) -> tuple[bool, str]:
    return _run(["git", "pull", "--ff-only"], folder)


def stage_file(folder: str, file_path: str) -> tuple[bool, str]:
    return _run(["git", "add", "--", file_path], folder)


def unstage_file(folder: str, file_path: str) -> tuple[bool, str]:
    return _run(["git", "restore", "--staged", "--", file_path], folder)


def stage_all(folder: str) -> tuple[bool, str]:
    return _run(["git", "add", "-A"], folder)


def has_staged_changes(folder: str) -> bool:
    """True se há algo staged pronto pra commit."""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=folder,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    # rc != 0 significa que há diferenças staged
    return r.returncode != 0


def commit(folder: str, message: str) -> tuple[bool, str]:
    """Cria commit com a mensagem. Caller deve garantir staging antes."""
    if not message.strip():
        return False, "mensagem vazia"
    return _run(["git", "commit", "-m", message], folder)


def unstage_all(folder: str) -> tuple[bool, str]:
    """`git reset HEAD --` — tira tudo do staging area."""
    return _run(["git", "reset", "HEAD", "--"], folder)


def discard_unstaged(folder: str, file_path: str) -> tuple[bool, str]:
    """Descarta mudanças unstaged do arquivo (rollback pro HEAD).
    Destrutivo — caller deve confirmar com o usuário antes."""
    return _run(["git", "restore", "--", file_path], folder)


def delete_untracked(folder: str, file_path: str) -> tuple[bool, str]:
    """Remove arquivo untracked do disco. Destrutivo."""
    import os
    full = os.path.join(folder, file_path)
    try:
        if os.path.isfile(full):
            os.remove(full)
            return True, ""
        return False, f"não é arquivo: {full}"
    except OSError as e:
        return False, str(e)


def checkout_new_branch(
    folder: str, branch: str, base: str | None = None
) -> tuple[bool, str]:
    """`git checkout -b <branch> [<base>]` no folder.

    Cria a branch nova e troca pra ela in-place (sem worktree). Mantém
    mudanças não-commitadas (git carrega elas pra nova branch se não
    houver conflito). Caller deve avisar o usuário se necessário.
    """
    if not branch.strip():
        return False, "branch inválida (vazia)"
    args = ["git", "checkout", "-b", branch]
    if base:
        args.append(base)
    return _run(args, folder)
