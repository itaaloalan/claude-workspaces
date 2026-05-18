"""Builder de prompts para o Claude gerar RunnerConfigs."""

from __future__ import annotations

from ..models import Workspace


def build_generate_prompt(workspace: Workspace, hint: str = "") -> str:
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nHint do usuário: {hint}\n" if hint.strip() else ""
    return (
        f"Leia `docs/runners-spec.md` deste repositório (claude-workspaces) e "
        f"gere a configuração de um Runner para o workspace abaixo.\n\n"
        f"Workspace: {workspace.name}\n"
        f"Pastas:\n{folders}\n"
        f"{hint_block}\n"
        "Responda APENAS com o JSON do RunnerConfig (sem cercas markdown, sem "
        "comentários). Campos: name, start_cmd, stop_cmd, restart_cmd, cwd "
        "(opcional), enabled. Comandos devem ser foreground quando possível e "
        "responder a SIGHUP/SIGTERM. Para servidores que rodam em background "
        "(ex: glassfish), use stop_cmd e restart_cmd explícitos."
    )
