"""Ações git escritas que mutam o repo (pull/fetch/commit/stage).

Cada função roda em foreground via subprocess com timeout e devolve
(success: bool, output: str) — caller decide se mostra QMessageBox.
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

TIMEOUT_S = 60
PUSH_TIMEOUT_S = 120

# SHA da árvore vazia do git — base de diff quando o commit é raiz (sem pai).
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


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


def list_branches(folder: str) -> tuple[list[str], str]:
    """Lista branches locais; retorna (branches, current). Vazio em erro."""
    if not Path(folder).is_dir():
        return [], ""
    try:
        r = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
        c = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], ""
    if r.returncode != 0:
        return [], ""
    branches = [b.strip() for b in r.stdout.splitlines() if b.strip()]
    current = c.stdout.strip() if c.returncode == 0 else ""
    return branches, current


def checkout_branch(folder: str, branch: str) -> tuple[bool, str]:
    """`git checkout <branch>` — troca pra branch existente."""
    if not branch.strip():
        return False, "branch inválida (vazia)"
    return _run(["git", "checkout", branch], folder)


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


# ---------- preview de push (estilo IntelliJ "Push Commits") ----------


@dataclass
class PushCommit:
    """Um commit ainda não enviado pro remote."""

    sha: str
    short: str
    subject: str
    author: str
    date: str


@dataclass
class PushPreview:
    """O que um `git push` deste folder vai enviar.

    `error` preenchido quando não dá pra montar a prévia (não é repo, sem
    branch, etc). `has_upstream=False` significa que o push precisaria de
    `-u` pra criar o upstream.
    """

    folder: str
    name: str = ""
    branch: str = ""
    remote: str = "origin"
    upstream: str = ""
    has_upstream: bool = False
    commits: list[PushCommit] = field(default_factory=list)
    files: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.commits


def _git_out(args: list[str], cwd: str, timeout: int = 5) -> tuple[bool, str]:
    """rev-parse/log/diff — leitura rápida, timeout curto."""
    if not Path(cwd).is_dir():
        return False, ""
    try:
        r = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return r.returncode == 0, r.stdout


def push_preview(folder: str) -> PushPreview:
    """Monta a prévia dos commits/arquivos que um push enviaria.

    Com upstream: range = `<upstream>..HEAD`. Sem upstream: pega os commits
    de HEAD que não estão em nenhum remote (`--not --remotes`). Os arquivos
    são o diff acumulado entre o pai do commit mais antigo do range e HEAD.
    """
    pv = PushPreview(folder=folder, name=Path(folder).name)
    if not Path(folder).is_dir():
        pv.error = "pasta inexistente"
        return pv

    ok, branch = _git_out(["git", "symbolic-ref", "--short", "HEAD"], folder)
    pv.branch = branch.strip()
    if not ok or not pv.branch:
        pv.error = "HEAD destacado ou sem branch"
        return pv

    ok_up, upstream = _git_out(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        folder,
    )
    upstream = upstream.strip()
    if ok_up and upstream and "/" in upstream:
        pv.has_upstream = True
        pv.upstream = upstream
        pv.remote = upstream.split("/", 1)[0]
        rev_args = ["git", "rev-list", f"{upstream}..HEAD"]
    else:
        # Sem upstream: o push criaria a branch no remote enviando tudo que
        # ainda não está em nenhum remote conhecido.
        pv.remote = "origin"
        rev_args = ["git", "rev-list", "HEAD", "--not", "--remotes"]

    ok, out = _git_out(rev_args, folder)
    shas = [s for s in out.split() if s] if ok else []
    if not shas:
        return pv  # nada a enviar (is_empty=True)

    fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%ad"
    ok, log_out = _git_out(
        ["git", "log", f"--format={fmt}", "--date=short", "--no-walk", *shas],
        folder,
    )
    if ok:
        for line in log_out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) == 5:
                pv.commits.append(
                    PushCommit(parts[0], parts[1], parts[2], parts[3], parts[4])
                )

    # Diff acumulado: pai do commit mais antigo (último do rev-list) .. HEAD.
    base = f"{shas[-1]}^"
    ok, _ = _git_out(["git", "rev-parse", "--verify", "--quiet", base], folder)
    if not ok:
        base = EMPTY_TREE  # commit raiz, sem pai
    ok, diff_out = _git_out(
        ["git", "diff", "--name-status", "-z", f"{base}", "HEAD"], folder
    )
    if ok:
        pv.files = _parse_name_status_z(diff_out)
    return pv


def _parse_name_status_z(raw: str) -> list[tuple[str, str]]:
    """Parse de `git diff --name-status -z` → [(status, path), ...].

    Renomeados/copiados (R/C) ocupam 3 tokens (status, origem, destino);
    guardamos só o destino. -z usa NUL como separador."""
    tokens = [t for t in raw.split("\0") if t != ""]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        code = status[0] if status else ""
        if code in ("R", "C") and i + 2 < len(tokens):
            out.append((status, tokens[i + 2]))
            i += 3
        elif i + 1 < len(tokens):
            out.append((status, tokens[i + 1]))
            i += 2
        else:
            break
    return out


def push(
    folder: str,
    branch: str,
    remote: str = "origin",
    set_upstream: bool = False,
    follow_tags: bool = False,
) -> tuple[bool, str]:
    """`git push [-u] [--follow-tags] <remote> <branch>`."""
    if not branch.strip():
        return False, "branch inválida (vazia)"
    args = ["git", "push"]
    if set_upstream:
        args.append("-u")
    if follow_tags:
        args.append("--follow-tags")
    args += [remote, branch]
    return _run(args, folder)
