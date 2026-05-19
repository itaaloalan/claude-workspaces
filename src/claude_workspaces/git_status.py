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
# Cap pra não despejar megabytes de arquivo novo no QPlainTextEdit do diff.
MAX_DIFF_BYTES = 512 * 1024


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


def _parse_porcelain_v2(stdout: str) -> tuple[str, int, int, list[GitFile]]:
    """Parser do output de `git status --porcelain=v2 --branch -z`.

    Headers começam com `#`. Records: `1 ` (changed), `2 ` (renamed/copied,
    com path original como entry NUL seguinte), `? ` (untracked), `! `
    (ignored), `u ` (unmerged). XY usa `.` pra unmodified — convertemos pra
    espaço pra manter compat com o resto do código que checa `status[0] == " "`.
    """
    branch_head = "?"
    branch_oid = ""
    ahead = 0
    behind = 0
    files: list[GitFile] = []

    entries = stdout.split("\0")
    i = 0
    while i < len(entries):
        line = entries[i]
        i += 1
        if not line:
            continue
        if line.startswith("# branch.oid "):
            branch_oid = line[len("# branch.oid "):]
        elif line.startswith("# branch.head "):
            branch_head = line[len("# branch.head "):]
        elif line.startswith("# branch.ab "):
            parts = line[len("# branch.ab "):].split()
            if len(parts) == 2:
                try:
                    ahead = int(parts[0])  # "+N"
                    behind = -int(parts[1])  # "-M"
                except ValueError:
                    pass
        elif line.startswith("#"):
            continue
        elif line.startswith("1 "):
            # "1 XY sub mH mI mW hH hI path"
            parts = line.split(" ", 8)
            if len(parts) == 9:
                xy = parts[1].replace(".", " ")
                files.append(GitFile(status=xy, path=parts[8]))
        elif line.startswith("2 "):
            # "2 XY sub mH mI mW hH hI X<score> path" + próximo entry = orig path
            parts = line.split(" ", 9)
            if len(parts) == 10:
                xy = parts[1].replace(".", " ")
                files.append(GitFile(status=xy, path=parts[9]))
            if i < len(entries):
                i += 1  # consome path original
        elif line.startswith("? "):
            files.append(GitFile(status="??", path=line[2:]))
        elif line.startswith("u "):
            # "u XY sub m1 m2 m3 mW h1 h2 h3 path"
            parts = line.split(" ", 10)
            if len(parts) == 11:
                xy = parts[1].replace(".", " ")
                files.append(GitFile(status=xy, path=parts[10]))
        # `! ` ignorado: não pedimos `--ignored`, mas pula por segurança

    branch = branch_head
    if branch == "(detached)":
        short = branch_oid[:7] if branch_oid and branch_oid != "(initial)" else "?"
        branch = f"detached@{short}"
    return branch, ahead, behind, files


def get_status(folder: str) -> GitStatus:
    if not folder or not Path(folder).is_dir():
        return GitStatus(folder=folder, is_repo=False)
    try:
        r = _run(
            ["git", "status", "--porcelain=v2", "--branch", "-z"],
            folder,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return GitStatus(folder=folder, is_repo=False, error=str(e))
    if r.returncode != 0:
        # Não é repo (ou git falhou): exit 128 é o caso comum de
        # "not a git repository". Mantemos compat: is_repo=False sem erro.
        return GitStatus(folder=folder, is_repo=False)

    try:
        branch, ahead, behind, files = _parse_porcelain_v2(r.stdout)
        return GitStatus(
            folder=folder,
            is_repo=True,
            branch=branch,
            ahead=ahead,
            behind=behind,
            files=files,
        )
    except Exception as e:
        log.exception("parse porcelain v2 falhou em %s", folder)
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
        if len(r.stdout) > MAX_DIFF_BYTES:
            return (
                r.stdout[:MAX_DIFF_BYTES]
                + f"\n\n(... diff truncado em {MAX_DIFF_BYTES // 1024} KiB —"
                " abra o arquivo pra ver completo)"
            )
        return r.stdout
    # Vazio = pode ser untracked. Mostra o conteúdo com + na frente.
    abs_path = Path(folder) / file_path
    if abs_path.is_file():
        try:
            size = abs_path.stat().st_size
        except OSError as e:
            return f"(falha lendo arquivo: {e})"
        if size > MAX_DIFF_BYTES:
            return (
                f"(arquivo novo grande: {size // 1024} KiB — preview truncado)\n\n"
                + _read_prefixed(abs_path, MAX_DIFF_BYTES)
            )
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"(falha lendo arquivo: {e})"
        prefix_lines = "\n".join(f"+{line}" for line in text.splitlines())
        return f"(arquivo novo, sem versão anterior)\n\n{prefix_lines}"
    return "(sem alterações)"


def _read_prefixed(path: Path, max_bytes: int) -> str:
    try:
        with path.open("rb") as fh:
            blob = fh.read(max_bytes)
    except OSError as e:
        return f"(falha lendo arquivo: {e})"
    text = blob.decode("utf-8", errors="replace")
    return "\n".join(f"+{line}" for line in text.splitlines())
