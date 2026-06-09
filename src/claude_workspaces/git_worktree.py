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


def suggest_branch_name(prefix: str = "claude") -> str:
    prefix = (prefix or "claude").strip().strip("/") or "claude"
    return f"{prefix}/{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def safe_dir_name(branch: str) -> str:
    """Substitui caracteres problemáticos no nome da branch pra
    transformar em diretório válido."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", branch)


def worktree_base(repo_path: str) -> Path:
    repo = Path(repo_path)
    return repo.parent / (repo.name + ".claude")


def worktree_path_for(repo_path: str, branch: str) -> Path:
    return worktree_base(repo_path) / safe_dir_name(branch)


def repo_root(folder: str) -> str:
    """Raiz do worktree que contém `folder` (`git rev-parse --show-toplevel`).
    Resolve o caso de a pasta do workspace ser um SUBDIR do repo: o workspace
    sipepro aponta pra .../sipe/sipe/src, mas o .git e os worktrees vivem em
    .../sipe/sipe. "" se `folder` não está num repo git."""
    rc, out = _run(["git", "rev-parse", "--show-toplevel"], folder)
    return out.strip() if rc == 0 else ""


def add_worktree(
    repo_path: str,
    branch: str,
    base_branch: str | None = None,
    create_branch: bool = True,
) -> tuple[bool, str, Path]:
    """Cria worktree em <parent>/<repo>.claude/<safe-branch>.

    create_branch=True (default): `git worktree add -b <branch> <path> <base>`
    create_branch=False:           `git worktree add <path> <branch>` — checkout
                                    de branch existente em novo worktree.

    Retorna (ok, mensagem_de_erro, path).
    """
    dest = worktree_path_for(repo_path, branch)
    if dest.exists():
        return False, f"path já existe: {dest}", dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if create_branch:
        args = ["git", "worktree", "add", "-b", branch, str(dest)]
        if base_branch:
            args.append(base_branch)
    else:
        args = ["git", "worktree", "add", str(dest), branch]
    rc, out = _run(args, repo_path)
    if rc != 0:
        return False, out, dest
    return True, "", dest


def is_worktree_path(path: str) -> bool:
    """True se `path` é uma git worktree linkada (não o repo principal).

    Num repo normal `--git-dir == --git-common-dir`; numa worktree linkada o
    `--git-dir` aponta pra `.git/worktrees/<nome>` e diferem do common-dir.
    """
    rc1, gd = _run(["git", "rev-parse", "--git-dir"], path)
    rc2, gc = _run(["git", "rev-parse", "--git-common-dir"], path)
    if rc1 != 0 or rc2 != 0:
        return False
    a = (Path(path) / gd.strip()).resolve()
    b = (Path(path) / gc.strip()).resolve()
    return a != b


def resolve_git_dirs(folder: str) -> tuple[Path, Path] | None:
    """Resolve (git_dir, common_dir) de uma pasta, sem subprocess.

    Num repo normal `.git` é diretório e git_dir == common_dir. Numa worktree
    linkada `.git` é um ARQUIVO "gitdir: <path>" apontando para
    `<repo>/.git/worktrees/<nome>` (onde vivem HEAD/index/logs por-worktree);
    o common-dir (refs/heads compartilhado) vem do arquivo `commondir` dentro
    dele. Retorna None se a pasta não é um repo git.
    """
    dotgit = Path(folder) / ".git"
    if dotgit.is_dir():
        return dotgit, dotgit
    if not dotgit.is_file():
        return None
    try:
        content = dotgit.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    git_dir = Path(content[len("gitdir:"):].strip())
    if not git_dir.is_absolute():
        git_dir = (Path(folder) / git_dir).resolve()
    common_dir = git_dir
    commondir_file = git_dir / "commondir"
    if commondir_file.is_file():
        try:
            rel = commondir_file.read_text(encoding="utf-8").strip()
        except OSError:
            rel = ""
        if rel:
            common_dir = (
                Path(rel) if Path(rel).is_absolute() else (git_dir / rel).resolve()
            )
    return git_dir, common_dir


def current_branch(path: str) -> str:
    """Nome da branch atual em `path` ("" se detached/erro)."""
    rc, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path)
    return out.strip() if rc == 0 else ""


def list_local_branches(repo_path: str) -> list[str]:
    """Lista nomes das branches locais (ordenadas por uso recente)."""
    rc, out = _run(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)",
            "refs/heads",
        ],
        repo_path,
    )
    if rc != 0:
        return []
    return [b.strip() for b in out.splitlines() if b.strip()]


def remove_worktree(worktree_path: str) -> tuple[bool, str]:
    """Remove o worktree. Pede ao git pra fazer cleanup do registro
    interno + remove o diretório."""
    # Descobre o repo principal via --git-common-dir (sempre aponta pro
    # .git principal mesmo quando rodado de dentro de um worktree).
    # --show-toplevel não serve aqui — devolve o próprio worktree.
    rc, out = _run(["git", "rev-parse", "--git-common-dir"], worktree_path)
    if rc != 0:
        return False, f"não foi possível resolver o repo: {out}"
    common_dir = Path(out.strip())
    if not common_dir.is_absolute():
        common_dir = (Path(worktree_path) / common_dir).resolve()
    main_repo = str(common_dir.parent)
    if Path(main_repo).resolve() == Path(worktree_path).resolve():
        return False, "esse path é o repo principal, não um worktree"
    rc, out = _run(
        ["git", "worktree", "remove", "--force", worktree_path], main_repo
    )
    return rc == 0, out


def dirty_files(worktree_path: str) -> list[str]:
    """Linhas do `git status --short` do worktree ([] se limpo/erro)."""
    rc, out = _run(["git", "status", "--short"], worktree_path)
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def unpushed_commits(worktree_path: str) -> list[str]:
    """Commits do HEAD que não estão em NENHUM remote (oneline)."""
    rc, out = _run(
        ["git", "log", "--oneline", "HEAD", "--not", "--remotes"],
        worktree_path,
    )
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def delete_branch(repo_path: str, branch: str) -> tuple[bool, str]:
    """`git branch -d` (sem -D): falha se a branch não estiver mergeada."""
    rc, out = _run(["git", "branch", "-d", branch], repo_path)
    return rc == 0, out


def remap_into_worktree(path: str, worktree_dir: str) -> str:
    """Caminho equivalente a `path` dentro de `worktree_dir`, quando ambos são
    do MESMO repo mas em checkouts diferentes — preservando o subdir relativo à
    raiz do checkout de `path`. Pra runners de console com cwd FIXO no checkout
    principal seguirem o worktree adotado pelo console.

    "" quando: repos diferentes (ex.: módulo num repo sem worktree — fica no
    main), `path` já está nesse checkout, ou o subdir não existe no worktree.
    Ex.: path=.../sipe/sipe/src/api, worktree=.../sipe/sipe.claude/feat
         → .../sipe/sipe.claude/feat/src/api
    """
    if not path or not worktree_dir:
        return ""
    root = repo_root(path)
    wt_root = repo_root(worktree_dir)
    if not root or not wt_root:
        return ""
    root_p = Path(root).resolve()
    wt_p = Path(wt_root).resolve()
    if root_p == wt_p:
        return ""  # mesmo checkout — nada a remapear
    r_dirs = resolve_git_dirs(root)
    w_dirs = resolve_git_dirs(wt_root)
    if r_dirs is None or w_dirs is None:
        return ""
    if r_dirs[1].resolve() != w_dirs[1].resolve():
        return ""  # repos diferentes (common-dir distinto) → sem remap
    try:
        sub = Path(path).resolve().relative_to(root_p)
    except ValueError:
        return ""
    candidate = wt_p / sub
    return str(candidate) if candidate.is_dir() else ""


def translate_dir_for_repo(target_dir: str, repo_folder: str) -> str:
    """Equivalente de `target_dir` (dir/worktree de ALGUM repo) no repo
    `repo_folder` — pra workspaces multi-repo: apontar runners pro worktree
    de um console não pode jogar um runner do map-web dentro do map-api.

    - target pertence ao próprio repo (mesmo common-dir) → o próprio target;
    - senão, worktree de MESMA BRANCH em `repo_folder` → path dele;
    - senão → "" (sem equivalente; quem chama mantém o dir base do repo).
    """
    if not target_dir or not repo_folder:
        return ""
    t_dirs = resolve_git_dirs(target_dir)
    r_dirs = resolve_git_dirs(repo_folder)
    if t_dirs is None or r_dirs is None:
        return ""
    if t_dirs[1].resolve() == r_dirs[1].resolve():
        return target_dir
    branch = current_branch(target_dir)
    if not branch:
        return ""
    for wt in list_worktrees(repo_folder):
        wt_branch = wt.get("branch", "")
        if wt_branch.startswith("refs/heads/"):
            wt_branch = wt_branch[len("refs/heads/"):]
        if wt_branch == branch and wt.get("worktree"):
            return wt["worktree"]
    return ""


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
