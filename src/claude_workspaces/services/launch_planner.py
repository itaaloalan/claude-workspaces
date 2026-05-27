"""Decide cwd + extras + worktree pra um launch do Claude.

Lógica pura(-ish): recebe escolhas do dialog, monta o LaunchPlan,
cria worktree quando pedido. Sem Qt — só git_worktree.add_worktree.

Permite testar o fluxo de decisão sem subir a UI.
"""

from dataclasses import dataclass

from ..git_actions import checkout_new_branch
from ..git_worktree import add_worktree


@dataclass
class LaunchPlan:
    cwd: str
    extras: list[str]
    worktree_label: str = ""
    # True quando o cwd é um git worktree isolado (isolate_worktree).
    # Distingue do caso "branch in-place" — ambos têm worktree_label, mas
    # só o worktree roda numa árvore separada.
    is_worktree: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.cwd)


def plan_from_dialog(
    selected_folders: list[str],
    isolate_worktree: bool,
    create_branch: bool,
    branch_name: str,
    base_branch: str,
    *,
    worktree_creator=add_worktree,
    branch_checkout=checkout_new_branch,
) -> LaunchPlan:
    """Mapeia escolhas do LaunchClaudeDialog pra LaunchPlan.

    4 combinações:
      isolate=Y + new_branch=Y → worktree com -b <branch> <base>
      isolate=Y + new_branch=N → worktree em branch existente
      isolate=N + new_branch=Y → git checkout -b <branch> no cwd (in-place)
      isolate=N + new_branch=N → cwd e branch atual, sem mudar nada

    worktree_creator e branch_checkout são injetáveis pra testes.
    """
    if not selected_folders:
        return LaunchPlan(cwd="", extras=[], error="nenhuma pasta selecionada")

    cwd = selected_folders[0]
    extras = list(selected_folders[1:])
    label = ""
    branch = (branch_name or "").strip()
    base = (base_branch or "").strip() or None

    if isolate_worktree:
        if not branch:
            return LaunchPlan(
                cwd=cwd, extras=extras, error="branch inválida (vazia)"
            )
        effective_base = base if create_branch else None
        ok, msg, dest = worktree_creator(
            cwd, branch, effective_base, create_branch=create_branch
        )
        if not ok:
            return LaunchPlan(
                cwd=cwd, extras=extras, error=f"worktree falhou: {msg}"
            )
        cwd = str(dest)
        label = f" · {branch}"
        return LaunchPlan(
            cwd=cwd, extras=extras, worktree_label=label, is_worktree=True
        )
    elif create_branch:
        # Sem worktree, criar branch in-place via `git checkout -b`
        if not branch:
            return LaunchPlan(
                cwd=cwd, extras=extras, error="branch inválida (vazia)"
            )
        ok, msg = branch_checkout(cwd, branch, base)
        if not ok:
            return LaunchPlan(
                cwd=cwd, extras=extras, error=f"checkout falhou: {msg}"
            )
        label = f" · {branch}"

    return LaunchPlan(cwd=cwd, extras=extras, worktree_label=label)


def build_claude_argv(
    claude_command: str,
    extra_args: list[str],
    extras: list[str],
    resume_session_id: str = "",
) -> list[str]:
    """Monta argv pra rodar claude com os parâmetros corretos.
    Inclui --resume quando resume_session_id ≠ '' e --add-dir pra cada
    pasta em extras. Pura."""
    argv: list[str] = [claude_command, *extra_args]
    if resume_session_id:
        argv.extend(["--resume", resume_session_id])
    for extra in extras:
        argv.extend(["--add-dir", extra])
    return argv


def build_opencode_argv(
    command: str,
    extra_args: list[str],
    extras: list[str],
    resume_session_id: str = "",
) -> list[str]:
    """Monta argv pra rodar opencode.
    opencode aceita o diretório como posicional e usa -s/--session pra
    continuar uma sessão. Sem --add-dir — usa o cwd + posicional."""
    argv: list[str] = [command, *extra_args]
    if resume_session_id:
        argv.extend(["-s", resume_session_id])
    return argv


def build_ai_argv(
    backend: str,
    command: str,
    extra_args: list[str],
    extras: list[str],
    resume_session_id: str = "",
) -> list[str]:
    """Monta argv pro backend ativo."""
    if backend == "opencode":
        return build_opencode_argv(command, extra_args, extras, resume_session_id)
    return build_claude_argv(command, extra_args, extras, resume_session_id)
