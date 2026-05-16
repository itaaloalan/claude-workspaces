"""Descobre recursos do Claude Code: skills, agents e commands.

Hierarquia de origens (cada uma fornece os 3 tipos):
- user-scope:    ~/.claude/{skills,agents,commands}/
- plugin-scope:  ~/.claude/plugins/marketplaces/*/{external_plugins,plugins}/*/{skills,agents,commands}/
- project-scope: <workspace>/.claude/{skills,agents,commands}/

Estrutura física:
- skills: <base>/<nome>/SKILL.md          (subdir)
- agents: <base>/<nome>.md                (arquivo direto)
- commands: <base>/<nome>.md              (arquivo direto)

Parsing leve do frontmatter YAML pra pegar name + description.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_FRONT_LINE_RE = re.compile(r"^([\w-]+):\s*(.+?)\s*$")


KIND_SKILL = "skill"
KIND_AGENT = "agent"
KIND_COMMAND = "command"

KIND_LABEL_MAP = {
    KIND_SKILL: "Skill",
    KIND_AGENT: "Agente",
    KIND_COMMAND: "Comando",
}


@dataclass
class ClaudeItem:
    name: str
    description: str
    source: str  # "user", "project", "plugin:<name>"
    kind: str    # KIND_SKILL | KIND_AGENT | KIND_COMMAND
    path: Path

    @property
    def source_label(self) -> str:
        if self.source.startswith("plugin:"):
            return self.source.split(":", 1)[1]
        return self.source

    @property
    def invocation(self) -> str:
        """O que o usuário cola no Claude pra invocar.
        - skill: /name
        - command: /name
        - agent: name (não é slash, é nome do subagent)
        """
        return f"/{self.name}" if self.kind != KIND_AGENT else self.name


# Alias pra compatibilidade — código antigo usa Skill
Skill = ClaudeItem


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end].strip()
    out: dict[str, str] = {}
    for line in fm.splitlines():
        m = _FRONT_LINE_RE.match(line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            out[key] = val
    return out


def _read_item(
    md_path: Path, source: str, kind: str, fallback_name: str = ""
) -> ClaudeItem | None:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("falha lendo %s: %s", md_path, e)
        return None
    fm = _parse_frontmatter(text)
    name = fm.get("name") or fallback_name or md_path.stem
    description = fm.get("description") or ""
    return ClaudeItem(
        name=name, description=description, source=source, kind=kind, path=md_path
    )


def _list_skills_in(base: Path, source: str) -> list[ClaudeItem]:
    if not base.is_dir():
        return []
    out: list[ClaudeItem] = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.is_dir():
            for candidate in (entry / "SKILL.md", entry / "skill.md"):
                if candidate.exists():
                    item = _read_item(
                        candidate, source, KIND_SKILL, fallback_name=entry.name
                    )
                    if item:
                        out.append(item)
                    break
        elif entry.is_file() and entry.suffix == ".md" and entry.name != "README.md":
            item = _read_item(entry, source, KIND_SKILL)
            if item:
                out.append(item)
    return out


def _list_flat_in(base: Path, source: str, kind: str) -> list[ClaudeItem]:
    """Pra agents e commands: arquivos .md direto no diretório."""
    if not base.is_dir():
        return []
    out: list[ClaudeItem] = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.is_file() and entry.suffix == ".md" and entry.name != "README.md":
            item = _read_item(entry, source, kind)
            if item:
                out.append(item)
    return out


# ----- user scope -----

def list_user_skills() -> list[ClaudeItem]:
    return _list_skills_in(Path.home() / ".claude" / "skills", "user")


def list_user_agents() -> list[ClaudeItem]:
    return _list_flat_in(Path.home() / ".claude" / "agents", "user", KIND_AGENT)


def list_user_commands() -> list[ClaudeItem]:
    return _list_flat_in(Path.home() / ".claude" / "commands", "user", KIND_COMMAND)


# ----- plugin scope (marketplace) -----

def _walk_plugin_roots() -> list[tuple[str, Path]]:
    """Retorna [(plugin_name, plugin_root), ...] varrendo marketplaces."""
    base = Path.home() / ".claude" / "plugins" / "marketplaces"
    if not base.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    try:
        for marketplace in base.iterdir():
            if not marketplace.is_dir():
                continue
            for sub in ("plugins", "external_plugins"):
                container = marketplace / sub
                if not container.is_dir():
                    continue
                for plugin in container.iterdir():
                    if plugin.is_dir():
                        found.append((plugin.name, plugin))
    except OSError:
        pass
    return found


def list_plugin_skills() -> list[ClaudeItem]:
    out: list[ClaudeItem] = []
    for name, root in _walk_plugin_roots():
        out.extend(_list_skills_in(root / "skills", f"plugin:{name}"))
    return out


def list_plugin_agents() -> list[ClaudeItem]:
    out: list[ClaudeItem] = []
    for name, root in _walk_plugin_roots():
        out.extend(_list_flat_in(root / "agents", f"plugin:{name}", KIND_AGENT))
    return out


def list_plugin_commands() -> list[ClaudeItem]:
    out: list[ClaudeItem] = []
    for name, root in _walk_plugin_roots():
        out.extend(_list_flat_in(root / "commands", f"plugin:{name}", KIND_COMMAND))
    return out


# ----- project scope -----

def list_project_skills(workspace_folders: list[str] | None) -> list[ClaudeItem]:
    if not workspace_folders:
        return []
    out: list[ClaudeItem] = []
    for folder in workspace_folders:
        out.extend(_list_skills_in(Path(folder) / ".claude" / "skills", "project"))
    return out


def list_project_agents(workspace_folders: list[str] | None) -> list[ClaudeItem]:
    if not workspace_folders:
        return []
    out: list[ClaudeItem] = []
    for folder in workspace_folders:
        out.extend(_list_flat_in(
            Path(folder) / ".claude" / "agents", "project", KIND_AGENT
        ))
    return out


def list_project_commands(workspace_folders: list[str] | None) -> list[ClaudeItem]:
    if not workspace_folders:
        return []
    out: list[ClaudeItem] = []
    for folder in workspace_folders:
        out.extend(_list_flat_in(
            Path(folder) / ".claude" / "commands", "project", KIND_COMMAND
        ))
    return out


def list_all_items(workspace_folders: list[str] | None = None) -> list[ClaudeItem]:
    """Tudo agregado, dedup por (kind, name) com prioridade
    project > user > plugin."""
    everything: list[ClaudeItem] = []
    everything += list_plugin_skills()
    everything += list_plugin_agents()
    everything += list_plugin_commands()
    everything += list_user_skills()
    everything += list_user_agents()
    everything += list_user_commands()
    everything += list_project_skills(workspace_folders)
    everything += list_project_agents(workspace_folders)
    everything += list_project_commands(workspace_folders)
    deduped: dict[tuple[str, str], ClaudeItem] = {}
    for item in everything:
        # ordem garante que project sobrescreve user que sobrescreve plugin
        deduped[(item.kind, item.name)] = item
    return sorted(
        deduped.values(),
        key=lambda i: (i.kind, i.name.lower()),
    )


# Compat antigo
def list_all_skills(workspace_folders: list[str] | None = None) -> list[ClaudeItem]:
    """Mantido pra compat — devolve tudo (skills + agents + commands)."""
    return list_all_items(workspace_folders)
