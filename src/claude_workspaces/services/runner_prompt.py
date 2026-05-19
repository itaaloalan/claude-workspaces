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

    Mantemos o prompt enxuto porque o Claude CLI 2.1.x descarta o
    argumento posicional silenciosamente quando `--add-dir` está
    presente — então o launcher chama claude sem `--add-dir`, e o
    Claude lê os paths absolutos (spec + pastas do workspace) via Read
    (`--dangerously-skip-permissions` libera leitura fora do cwd).
    """
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nHint do usuário: {hint}\n" if hint.strip() else ""
    out_path = pending_runner_path(workspace)
    spec_ref = (
        f"`{spec_path}` (caminho absoluto — use Read direto)"
        if spec_path
        else "`docs/runners-spec.md` deste repositório (claude-workspaces)"
    )
    return (
        f"Leia {spec_ref} e siga as instruções de investigação + formato "
        f"de saída descritas lá pra gerar a configuração de Runner do "
        f"workspace abaixo.\n\n"
        f"Workspace: {workspace.name}\n"
        f"Pastas (inspecione com Glob/LS/Read usando os paths absolutos):\n{folders}\n"
        f"{hint_block}\n"
        f"Salve o JSON resultante em: {out_path}\n"
        f"(crie diretórios pai com mkdir -p se necessário)"
    )
