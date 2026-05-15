"""Agrega uso de skills lendo as sessões do Claude Code.

Cada JSONL em ~/.claude/projects/*/ contém messages do tipo 'assistant'
com content[] incluindo tool_use blocks. Quando name=='Skill', o input
tem 'skill' e 'args' — registramos como uma invocação.

Funções públicas:
- aggregate_skill_usage() -> dict[skill_name, SkillUsage]
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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


def _iter_skill_invocations() -> Iterator[tuple[str, str, datetime | None]]:
    """Itera (skill_name, cwd, timestamp) sobre TODAS as sessões."""
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
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            if c.get("type") != "tool_use":
                                continue
                            if c.get("name") != "Skill":
                                continue
                            input_d = c.get("input") or {}
                            skill_name = input_d.get("skill")
                            if not isinstance(skill_name, str) or not skill_name:
                                continue
                            ts = _parse_timestamp(msg.get("timestamp", ""))
                            cwd = msg.get("cwd", "") or ""
                            yield (skill_name, cwd, ts)
            except OSError as e:
                log.debug("Skip %s: %s", jsonl, e)
                continue


def aggregate_skill_usage() -> dict[str, SkillUsage]:
    out: dict[str, SkillUsage] = {}
    for name, cwd, ts in _iter_skill_invocations():
        u = out.get(name)
        if u is None:
            u = SkillUsage(name=name)
            out[name] = u
        u.count += 1
        if ts is not None and (u.last_used is None or ts > u.last_used):
            u.last_used = ts
        if cwd:
            u.by_workspace[cwd] = u.by_workspace.get(cwd, 0) + 1
    return out
