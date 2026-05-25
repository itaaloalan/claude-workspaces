"""Builder de prompts para o Claude gerar RunnerConfigs."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import RunnerConfig, Workspace


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


def build_edit_prompt(
    workspace: Workspace,
    runner: RunnerConfig,
    hint: str = "",
    recent_output: str = "",
    spec_path: str | Path | None = None,
) -> str:
    """Prompt pra editar UM runner existente, preservando o nome.

    Diferente de `build_generate_prompt` (que regenera o workspace
    inteiro), aqui o Claude recebe a config atual do runner + a saída/erro
    recente dele e deve devolver SÓ esse runner atualizado no draft. O
    reload faz merge por nome — manter o mesmo `name` substitui o runner
    no lugar, sem mexer nos outros.
    """
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nO que o usuário quer ajustar: {hint}\n" if hint.strip() else ""
    out_path = pending_runner_path(workspace)
    spec_ref = (
        f"`{spec_path}` (caminho absoluto — use Read direto)"
        if spec_path
        else "`docs/runners-spec.md` deste repositório (claude-workspaces)"
    )
    current = json.dumps(
        {
            k: v
            for k, v in runner.to_dict().items()
            if k not in ("id", "console_session_id", "gen_session_id", "gen_cwd")
        },
        indent=2,
        ensure_ascii=False,
    )
    output_block = (
        f"\nSaída/erro recente deste runner (use pra diagnosticar):\n"
        f"```\n{recent_output.strip()[-6000:]}\n```\n"
        if recent_output.strip()
        else "\n(O runner não tem saída recente registrada.)\n"
    )
    return (
        f"Leia {spec_ref} e ajuste o runner abaixo do workspace "
        f"'{workspace.name}', seguindo o formato de saída descrito no spec.\n\n"
        f"Config atual deste runner:\n```json\n{current}\n```\n"
        f"{output_block}"
        f"{hint_block}\n"
        f"Pastas do workspace (inspecione com Glob/LS/Read usando os paths absolutos):\n{folders}\n\n"
        f"IMPORTANTE: mantenha o mesmo \"name\" (\"{runner.name}\") — o reload "
        f"faz merge por nome e substitui este runner no lugar. Devolva APENAS "
        f"este runner (uma entrada na lista \"runners\").\n"
        f"Salve o JSON resultante em: {out_path}\n"
        f"(crie diretórios pai com mkdir -p se necessário)"
    )
