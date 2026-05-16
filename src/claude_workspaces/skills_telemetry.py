"""Agrega uso de skills E agentes lendo as sessões do Claude Code.

Cada JSONL em ~/.claude/projects/*/ contém messages do tipo 'assistant'
com content[] incluindo tool_use blocks:
- name=='Skill' → input.skill registra como uso de skill
- name=='Task'  → input.subagent_type registra como uso de agente

Funções públicas:
- aggregate_skill_usage() -> dict[skill_name, SkillUsage]    (compat antigo)
- aggregate_usage() -> dict[(kind, name), SkillUsage]        (novo)
- find_zombies(items, usage, threshold_days) -> list[ClaudeItem]
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .skills_discovery import KIND_AGENT, KIND_SKILL, ClaudeItem

log = logging.getLogger(__name__)


@dataclass
class SkillUsage:
    name: str
    count: int = 0
    last_used: datetime | None = None
    by_workspace: dict[str, int] = field(default_factory=dict)

    def last_used_label(self) -> str:
        if not self.last_used:
            return ""
        now = datetime.now(UTC)
        delta = now - self.last_used
        days = delta.days
        if days <= 0:
            hours = int(delta.total_seconds() // 3600)
            if hours <= 0:
                return "agora"
            return f"{hours}h atrás"
        if days == 1:
            return "ontem"
        if days < 7:
            return f"{days}d atrás"
        if days < 30:
            return f"{days // 7}sem atrás"
        return self.last_used.strftime("%d/%m/%Y")


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _iter_invocations() -> Iterator[tuple[str, str, str, datetime | None]]:
    """Itera (kind, name, cwd, timestamp) sobre TODAS as sessões.

    Skill: tool_use name=='Skill' → input.skill
    Agent: tool_use name=='Task'  → input.subagent_type
    """
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return
    try:
        projects = list(base.iterdir())
    except OSError:
        return
    for proj in projects:
        if not proj.is_dir():
            continue
        for jsonl in proj.glob("*.jsonl"):
            try:
                with jsonl.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if msg.get("type") != "assistant":
                            continue
                        inner = msg.get("message")
                        if not isinstance(inner, dict):
                            continue
                        content = inner.get("content")
                        if not isinstance(content, list):
                            continue
                        ts = _parse_timestamp(msg.get("timestamp", ""))
                        cwd = msg.get("cwd", "") or ""
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            if c.get("type") != "tool_use":
                                continue
                            tool_name = c.get("name")
                            input_d = c.get("input") or {}
                            if tool_name == "Skill":
                                skill = input_d.get("skill")
                                if isinstance(skill, str) and skill:
                                    yield (KIND_SKILL, skill, cwd, ts)
                            elif tool_name == "Task":
                                agent = input_d.get("subagent_type")
                                if isinstance(agent, str) and agent:
                                    yield (KIND_AGENT, agent, cwd, ts)
            except OSError as e:
                log.debug("Skip %s: %s", jsonl, e)
                continue


def aggregate_usage() -> dict[tuple[str, str], SkillUsage]:
    """Agrega uso por (kind, name). kind ∈ {KIND_SKILL, KIND_AGENT}."""
    out: dict[tuple[str, str], SkillUsage] = {}
    for kind, name, cwd, ts in _iter_invocations():
        key = (kind, name)
        u = out.get(key)
        if u is None:
            u = SkillUsage(name=name)
            out[key] = u
        u.count += 1
        if ts is not None and (u.last_used is None or ts > u.last_used):
            u.last_used = ts
        if cwd:
            u.by_workspace[cwd] = u.by_workspace.get(cwd, 0) + 1
    return out


def aggregate_skill_usage() -> dict[str, SkillUsage]:
    """Compat antigo: só skills, keyed por name."""
    return {
        name: u
        for (kind, name), u in aggregate_usage().items()
        if kind == KIND_SKILL
    }


def find_zombies(
    items: list[ClaudeItem],
    usage: dict[tuple[str, str], SkillUsage],
    threshold_days: int = 30,
) -> list[ClaudeItem]:
    """Devolve itens (skills/agents) que nunca foram usados OU não foram
    usados nos últimos `threshold_days` dias.

    Commands não são incluídos (não temos como detectar uso confiável
    deles via JSONL — usuário digita texto e Claude responde sem
    indicação distinta de slash command).
    """
    cutoff = datetime.now(UTC) - timedelta(days=threshold_days)
    zombies: list[ClaudeItem] = []
    for item in items:
        if item.kind not in (KIND_SKILL, KIND_AGENT):
            continue
        u = usage.get((item.kind, item.name))
        if u is None or u.count == 0:
            zombies.append(item)
        elif u.last_used is None or u.last_used < cutoff:
            zombies.append(item)
    return zombies
