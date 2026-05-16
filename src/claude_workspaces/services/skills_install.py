"""Copia uma skill/agente/comando entre escopos.

Casos típicos:
- Skill global → projeto:  ~/.claude/skills/X  →  <proj>/.claude/skills/X
- Plugin → global:         <plugin>/skills/X   →  ~/.claude/skills/X
- Skill projeto A → B:     <A>/.claude/skills/X → <B>/.claude/skills/X

Skills são pastas (SKILL.md + assets) — copia recursivo.
Agents/commands são arquivos .md — copia direto.

Não toca em frontmatter; apenas duplica os arquivos. Renomeação fica
pro editor visual.
"""

import logging
import shutil
from pathlib import Path

from ..errors import LaunchError
from ..skills_discovery import KIND_AGENT, KIND_COMMAND, KIND_SKILL, ClaudeItem

log = logging.getLogger(__name__)

SCOPE_USER = "user"
SCOPE_PROJECT = "project"


def dest_dir(scope: str, workspace_folder: str | None, kind: str) -> Path:
    """Pasta de destino baseada no escopo + tipo.

    user:    ~/.claude/{skills,agents,commands}
    project: <workspace_folder>/.claude/{skills,agents,commands}
    """
    sub = {
        KIND_SKILL: "skills",
        KIND_AGENT: "agents",
        KIND_COMMAND: "commands",
    }.get(kind)
    if not sub:
        raise LaunchError(f"tipo desconhecido: {kind}")
    if scope == SCOPE_USER:
        return Path.home() / ".claude" / sub
    if scope == SCOPE_PROJECT:
        if not workspace_folder:
            raise LaunchError("escopo 'project' requer workspace_folder")
        return Path(workspace_folder) / ".claude" / sub
    raise LaunchError(f"escopo desconhecido: {scope}")


def target_path(item: ClaudeItem, scope: str, workspace_folder: str | None = None) -> Path:
    """Caminho final onde o item será gravado.

    Skill → <dest_dir>/<name>/SKILL.md
    Agent/command → <dest_dir>/<name>.md
    """
    base = dest_dir(scope, workspace_folder, item.kind)
    if item.kind == KIND_SKILL:
        return base / item.name / "SKILL.md"
    return base / f"{item.name}.md"


def already_installed(item: ClaudeItem, scope: str, workspace_folder: str | None = None) -> bool:
    return target_path(item, scope, workspace_folder).exists()


def install_item(
    item: ClaudeItem,
    scope: str,
    workspace_folder: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Copia o item pro escopo destino e devolve o path criado.

    Raises:
        LaunchError: se item.kind for desconhecido, se destino existir
            e overwrite=False, ou se a cópia falhar.
    """
    target = target_path(item, scope, workspace_folder)
    if target.exists() and not overwrite:
        raise LaunchError(
            f"já existe em {target} — passe overwrite=True pra substituir"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if item.kind == KIND_SKILL:
            # Skill é uma pasta — copia tudo (SKILL.md + recursos)
            src_dir = item.path.parent
            dst_dir = target.parent
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
        else:
            shutil.copy2(item.path, target)
    except OSError as e:
        raise LaunchError(f"falha copiando pra {target}: {e}") from e
    log.info("Instalado %s (%s) em %s", item.name, item.kind, target)
    return target


def available_scopes(
    item: ClaudeItem, workspace_folder: str | None = None
) -> list[tuple[str, str | None, str]]:
    """Lista escopos onde o item ainda NÃO está, na forma
    [(scope, workspace_folder, label), ...].

    Pula o escopo de origem do item (não faz sentido instalar de novo).
    """
    out: list[tuple[str, str | None, str]] = []
    # Global ~/.claude — só se item não veio de lá
    if item.source != "user":
        already = already_installed(item, SCOPE_USER)
        suffix = " (já instalado)" if already else ""
        out.append((SCOPE_USER, None, f"Global (~/.claude){suffix}"))
    # Projeto atual — só se workspace tá selecionado e item não veio de lá
    if workspace_folder and item.source != "project":
        already = already_installed(item, SCOPE_PROJECT, workspace_folder)
        suffix = " (já instalado)" if already else ""
        out.append((
            SCOPE_PROJECT, workspace_folder,
            f"Projeto: {Path(workspace_folder).name}/.claude{suffix}",
        ))
    return out
