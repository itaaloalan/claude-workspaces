"""Builder de prompts para o Claude gerar RunnerConfigs."""

from __future__ import annotations

from pathlib import Path

from ..models import Workspace


def pending_runner_path(workspace: Workspace) -> Path:
    """Caminho onde o Claude deve salvar o JSON gerado.

    O botão 'Recarregar runners' da aba Runners lê desse arquivo e
    importa via runners_io.import_runners.
    """
    return (
        Path.home()
        / ".config"
        / "claude-workspaces"
        / "runner-drafts"
        / f"{workspace.id}.json"
    )


def build_generate_prompt(
    workspace: Workspace, hint: str = "", spec_path: str | Path | None = None
) -> str:
    """Prompt curto que aponta o Claude pra `docs/runners-spec.md`.

    Precisa ficar curto (~400 chars) porque o Claude CLI 2.1.x trava na
    PTY quando recebe `--add-dir` + prompt posicional grande (~> 500
    chars) — bug do CLI; toda a instrução de investigação/formato mora
    no spec, que o Claude lê via Read.
    """
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nHint do usuário: {hint}\n" if hint.strip() else ""
    out_path = pending_runner_path(workspace)
    spec_ref = (
        f"`{spec_path}`"
        if spec_path
        else "`docs/runners-spec.md` deste repositório (claude-workspaces)"
    )
    return (
        f"Leia {spec_ref} (caminho absoluto, disponível via --add-dir) e "
        f"siga as instruções de investigação + formato de saída descritas "
        f"lá pra gerar a configuração de Runner do workspace abaixo.\n\n"
        f"Workspace: {workspace.name}\n"
        f"Pastas:\n{folders}\n"
        f"{hint_block}\n"
        f"Salve o JSON resultante em: {out_path}\n"
        f"(crie diretórios pai com mkdir -p se necessário)"
    )
