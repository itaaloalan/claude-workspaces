"""Wrapper fino sobre `git` pra coletar branch + status porcelain por pasta.

Roda os comandos via subprocess com timeout curto pra não travar a UI se
um repo grande ou um diretório montado lento atrapalhar.
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


log = logging.getLogger(__name__)

TIMEOUT_S = 5


@dataclass
class GitFile:
    status: str  # 2 chars do porcelain (ex: "M ", " M", "??", "MM", "A ")
    path: str

    @property
    def is_staged(self) -> bool:
        return self.status[0] not in (" ", "?")

    @property
    def is_unstaged(self) -> bool:
        return self.status[1] != " "

    @property
    def is_untracked(self) -> bool:
        return self.status == "??"

    def label(self) -> str:
        s = self.status
        if s == "??":
            return "novo"
        if s == "MM":
            return "mod (idx+ws)"
        if s.startswith("M") or s.endswith("M"):
            return "modificado"
        if s.startswith("A") or s.endswith("A"):
            return "adicionado"
        if s.startswith("D") or s.endswith("D"):
            return "deletado"
        if s.startswith("R"):
            return "renomeado"
        if s.startswith("C"):
            return "copiado"
        return s.strip() or "?"


@dataclass
class GitStatus:
    folder: str
    is_repo: bool = False
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    files: list[GitFile] = field(default_factory=list)
    error: str | None = None

    @property
    def is_clean(self) -> bool:
        return self.is_repo and not self.files


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
    )


def get_status(folder: str) -> GitStatus:
    if not folder or not Path(folder).is_dir():
        return GitStatus(folder=folder, is_repo=False)
    try:
        r = _run(["git", "rev-parse", "--show-toplevel"], folder)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return GitStatus(folder=folder, is_repo=False, error=str(e))
    if r.returncode != 0:
        return GitStatus(folder=folder, is_repo=False)

    try:
        b = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], folder)
        branch = b.stdout.strip() if b.returncode == 0 else "?"
        if branch == "HEAD":
            # detached: pega o hash curto
            h = _run(["git", "rev-parse", "--short", "HEAD"], folder)
            branch = f"detached@{h.stdout.strip()}" if h.returncode == 0 else "detached"

        ahead, behind = 0, 0
        ab = _run(
            ["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"],
            folder,
        )
        if ab.returncode == 0:
            parts = ab.stdout.strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

        s = _run(["git", "status", "--porcelain=v1", "-z"], folder)
        files: list[GitFile] = []
        if s.returncode == 0 and s.stdout:
            # -z usa NUL como separador; cada entrada: "XY path[\0orig\0]"
            for entry in s.stdout.split("\0"):
                if len(entry) < 4:
                    continue
                status_code = entry[:2]
                path = entry[3:]
                files.append(GitFile(status=status_code, path=path))

        return GitStatus(
            folder=folder,
            is_repo=True,
            branch=branch,
            ahead=ahead,
            behind=behind,
            files=files,
        )
    except subprocess.TimeoutExpired as e:
        log.warning("git status timeout em %s", folder)
        return GitStatus(folder=folder, is_repo=True, error=str(e))
    except Exception as e:
        log.exception("git status falhou em %s", folder)
        return GitStatus(folder=folder, is_repo=True, error=str(e))


def get_diff(folder: str, file_path: str, staged: bool = False) -> str:
    """Devolve o diff do arquivo (relativo ao folder).
    - staged=True: diff entre index e HEAD (mudanças staged)
    - staged=False: diff entre working tree e index (mudanças unstaged)
    Para arquivos untracked, retorna o conteúdo cru com prefixo +."""
    args = ["git", "diff", "--no-color"]
    if staged:
        args.append("--cached")
    args.extend(["--", file_path])
    try:
        r = _run(args, folder)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"(erro ao rodar git diff: {e})"
    if r.returncode != 0:
        return f"(git diff falhou: {r.stderr.strip()})"
    if r.stdout:
        return r.stdout
    # Vazio = pode ser untracked. Mostra o conteúdo com + na frente.
    abs_path = Path(folder) / file_path
    if abs_path.is_file():
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"(falha lendo arquivo: {e})"
        prefix_lines = "\n".join(f"+{line}" for line in text.splitlines())
        return f"(arquivo novo, sem versão anterior)\n\n{prefix_lines}"
    return "(sem alterações)"
