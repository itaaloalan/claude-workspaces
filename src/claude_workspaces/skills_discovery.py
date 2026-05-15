"""Descobre skills disponíveis no Claude Code:
- ~/.claude/skills/<name>/SKILL.md  (user-scope)
- ~/.claude/plugins/<plugin>/skills/<name>/SKILL.md  (plugin-scope)
- <workspace>/.claude/skills/<name>/SKILL.md  (project-scope)

Parsing leve do frontmatter YAML pra pegar name + description.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path


log = logging.getLogger(__name__)

# Linha YAML simples — não tenta resolver YAML complexo
_FRONT_LINE_RE = re.compile(r'^([\w-]+):\s*(.+?)\s*$')


@dataclass
class Skill:
    name: str
    description: str
    source: str  # "user", "project", "plugin:<name>"
    path: Path

    @property
    def source_label(self) -> str:
        if self.source.startswith("plugin:"):
            return self.source.split(":", 1)[1]
        return self.source

    @property
    def invocation(self) -> str:
        """O texto que o usuário cola no Claude pra ativar essa skill."""
        return f"/{self.name}"


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
            # Tira aspas externas, simples e duplas
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            out[key] = val
    return out


def _read_skill(md_path: Path, source: str, fallback_name: str = "") -> Skill | None:
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("falha lendo skill %s: %s", md_path, e)
        return None
    fm = _parse_frontmatter(text)
    name = fm.get("name") or fallback_name or md_path.stem
    description = fm.get("description") or ""
    return Skill(name=name, description=description, source=source, path=md_path)


def _list_skills_in(base: Path, source: str) -> list[Skill]:
    if not base.is_dir():
        return []
    skills: list[Skill] = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.is_dir():
            # Convenção: skills/<nome>/SKILL.md
            for candidate in (entry / "SKILL.md", entry / "skill.md"):
                if candidate.exists():
                    s = _read_skill(candidate, source, fallback_name=entry.name)
                    if s:
                        skills.append(s)
                    break
        elif entry.is_file() and entry.suffix == ".md" and entry.name != "README.md":
            s = _read_skill(entry, source)
            if s:
                skills.append(s)
    return skills


def list_user_skills() -> list[Skill]:
    return _list_skills_in(Path.home() / ".claude" / "skills", "user")


def list_plugin_skills() -> list[Skill]:
    base = Path.home() / ".claude" / "plugins"
    if not base.is_dir():
        return []
    out: list[Skill] = []
    try:
        plugins = list(base.iterdir())
    except OSError:
        return []
    for plugin in plugins:
        if plugin.is_dir():
            out.extend(_list_skills_in(plugin / "skills", f"plugin:{plugin.name}"))
    return out


def list_project_skills(workspace_folders: list[str] | None) -> list[Skill]:
    if not workspace_folders:
        return []
    out: list[Skill] = []
    for folder in workspace_folders:
        out.extend(_list_skills_in(Path(folder) / ".claude" / "skills", "project"))
    return out


def list_all_skills(workspace_folders: list[str] | None = None) -> list[Skill]:
    """Agrega skills de todas as fontes. Dedup por nome com prioridade:
    project > user > plugin (project sobrescreve user, user sobrescreve plugin)."""
    everything = (
        list_plugin_skills()
        + list_user_skills()
        + list_project_skills(workspace_folders)
    )
    deduped: dict[str, Skill] = {}
    for s in everything:
        deduped[s.name] = s  # ordem garante prioridade pela inserção mais recente
    return sorted(deduped.values(), key=lambda s: s.name.lower())
