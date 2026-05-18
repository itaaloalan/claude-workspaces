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


def build_generate_prompt(workspace: Workspace, hint: str = "") -> str:
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nHint do usuário: {hint}\n" if hint.strip() else ""
    out_path = pending_runner_path(workspace)
    return (
        f"Leia `docs/runners-spec.md` deste repositório (claude-workspaces) e "
        f"gere a configuração de um Runner para o workspace abaixo.\n\n"
        f"Workspace: {workspace.name}\n"
        f"Pastas:\n{folders}\n"
        f"{hint_block}\n"
        "Gere o JSON do RunnerConfig com os campos: name, start_cmd, "
        "stop_cmd, restart_cmd, cwd (opcional), enabled. Comandos devem ser "
        "foreground quando possível e responder a SIGHUP/SIGTERM. Para "
        "servidores que rodam em background (ex: glassfish), use stop_cmd "
        "e restart_cmd explícitos.\n\n"
        f"IMPORTANTE — salve o resultado no arquivo:\n  {out_path}\n\n"
        "no formato esperado pelo import (envelope com a chave `runners`, "
        "uma lista):\n"
        '  {"runners": [ { ...config... } ]}\n\n'
        "Crie diretórios pai se necessário (mkdir -p). Depois de salvar, "
        "avise ao usuário que ele pode clicar em **Recarregar runners** "
        "na aba Runners do claude-workspaces para importar."
    )
