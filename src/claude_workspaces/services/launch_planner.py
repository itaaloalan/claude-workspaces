"""Decide cwd + extras + worktree pra um launch do Claude.

Lógica pura(-ish): recebe escolhas do dialog, monta o LaunchPlan,
cria worktree quando pedido. Sem Qt — só git_worktree.add_worktree.

Permite testar o fluxo de decisão sem subir a UI.
"""

from dataclasses import dataclass

from ..git_worktree import add_worktree


@dataclass
class LaunchPlan:
    cwd: str
    extras: list[str]
    worktree_label: str = ""
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
) -> LaunchPlan:
    """Mapeia escolhas do LaunchClaudeDialog pra LaunchPlan.

    - cwd = primeira pasta marcada; demais entram como --add-dir
    - se isolate: cria worktree em cwd (com -b <branch> ou checkout
      de branch existente); cwd vira o path do worktree
    - retorna .error preenchido em caso de falha (caller mostra dialog)

    worktree_creator é injetável pra testes (sem mexer em git real).
    """
    if not selected_folders:
        return LaunchPlan(cwd="", extras=[], error="nenhuma pasta selecionada")

    cwd = selected_folders[0]
    extras = list(selected_folders[1:])
    label = ""

    if isolate_worktree:
        branch = (branch_name or "").strip()
        if not branch:
            return LaunchPlan(
                cwd=cwd, extras=extras, error="branch inválida (vazia)"
            )
        base = (base_branch or "").strip() or None
        # Quando NÃO criamos a branch, base não se aplica
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
