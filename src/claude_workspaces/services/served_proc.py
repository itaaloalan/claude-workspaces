"""Detecção A — quem REALMENTE serve a porta roda do worktree esperado?

A pill da extensão diz "WORKTREE feat/x" com base no cwd que o app registrou
pra porta. Mas o processo que de fato escuta o localhost:PORT pode ter sido
subido de OUTRA pasta (repo principal / worktree antigo) — aí o badge mente e
você testa código stale. Aqui descobrimos o PID dono da porta (Linux: `ss`,
fallback `lsof`), lemos o cwd dele (/proc/PID/cwd) e comparamos o git-dir
absoluto com o cwd esperado. git-dir absoluto é por-worktree (.git/worktrees/<n>
nas linkadas, .git no principal), então a comparação é robusta a subpastas.

Conservador de propósito: só acusa mismatch quando AMBOS resolvem pra um
git-dir e eles diferem. PID não achado / served fora de repo git → sem aviso
(não falsear).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

log = logging.getLogger(__name__)

_PID_RE = re.compile(r"pid=(\d+)")


def _run(argv: list[str], cwd: str | None = None, timeout: float = 2.0) -> tuple[int, str]:
    try:
        p = subprocess.run(  # noqa: S603 — argv fixo, sem shell
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def listening_pid(port: int) -> int | None:
    """PID que escuta TCP nesta porta (do usuário atual). None se nenhum."""
    if port <= 0:
        return None
    # ss é o padrão moderno; -H sem cabeçalho, -p inclui o processo dono.
    rc, out = _run(["ss", "-ltnpH", f"sport = :{port}"])
    if rc == 0 and out.strip():
        m = _PID_RE.search(out)
        if m:
            return int(m.group(1))
    # Fallback: lsof (alguns sistemas sem ss com -p).
    rc, out = _run(["lsof", "-ti", f"tcp:{port}", "-s", "TCP:LISTEN"])
    if rc == 0:
        for line in out.split():
            line = line.strip()
            if line.isdigit():
                return int(line)
    return None


def process_cwd(pid: int) -> str | None:
    """cwd do processo via /proc/PID/cwd (Linux). None se inacessível."""
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _abs_git_dir(path: str) -> str | None:
    """git-dir absoluto a partir de `path` (sobe das subpastas). Identidade
    única do worktree: .git/worktrees/<nome> (linkada) ou .git (principal)."""
    if not path:
        return None
    rc, out = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=path)
    if rc != 0:
        return None
    out = out.strip()
    return out or None


def served_mismatch(expected_cwd: str, port: int) -> dict:
    """Resolve quem serve a porta e diz se roda de um worktree diferente do
    `expected_cwd`. Campos:
      served_pid, served_cwd: do processo que escuta a porta (ou None);
      served_mismatch: True só quando ambos os git-dir resolvem e diferem.
    """
    info: dict = {
        "served_pid": None,
        "served_cwd": None,
        "served_mismatch": False,
    }
    if not expected_cwd or port <= 0:
        return info
    pid = listening_pid(port)
    if pid is None:
        return info
    info["served_pid"] = pid
    scwd = process_cwd(pid)
    info["served_cwd"] = scwd
    if not scwd:
        return info
    exp_gd = _abs_git_dir(expected_cwd)
    srv_gd = _abs_git_dir(scwd)
    if exp_gd and srv_gd and exp_gd != srv_gd:
        info["served_mismatch"] = True
    return info
