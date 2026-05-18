"""Parser do CHANGELOG.md no formato Keep a Changelog.

Lê o arquivo CHANGELOG.md na raiz do repo (ou do pacote instalado) e devolve
uma lista de `Release` em ordem do mais novo pro mais antigo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


@dataclass
class Release:
    version: str
    date: str
    sections: dict[str, list[str]] = field(default_factory=dict)
    """Mapa de cabeçalho de seção (ex.: "Adicionado", "Corrigido") pra bullets."""

    @property
    def body_markdown(self) -> str:
        parts: list[str] = []
        for header, bullets in self.sections.items():
            parts.append(f"### {header}")
            parts.extend(f"- {b}" for b in bullets)
            parts.append("")
        return "\n".join(parts).strip()


_VERSION_HEADER_RE = re.compile(
    r"^##\s*\[?(?P<ver>\d+\.\d+\.\d+(?:[-+][\w.]+)?)\]?\s*[—–-]?\s*(?P<date>.*)$"
)
_SECTION_RE = re.compile(r"^###\s+(?P<name>.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")


def parse_changelog(text: str) -> list[Release]:
    releases: list[Release] = []
    current: Release | None = None
    section_name: str | None = None
    bullet_buf: list[str] | None = None

    def flush_bullet() -> None:
        nonlocal bullet_buf
        if current is not None and section_name and bullet_buf:
            joined = " ".join(line.strip() for line in bullet_buf).strip()
            current.sections.setdefault(section_name, []).append(joined)
        bullet_buf = None

    for raw in text.splitlines():
        line = raw.rstrip()
        m_ver = _VERSION_HEADER_RE.match(line)
        if m_ver:
            flush_bullet()
            current = Release(
                version=m_ver.group("ver"),
                date=m_ver.group("date").strip(),
            )
            releases.append(current)
            section_name = None
            continue

        if current is None:
            continue

        m_sec = _SECTION_RE.match(line)
        if m_sec:
            flush_bullet()
            section_name = m_sec.group("name").strip()
            current.sections.setdefault(section_name, [])
            continue

        m_bul = _BULLET_RE.match(line)
        if m_bul:
            flush_bullet()
            bullet_buf = [m_bul.group("text")]
            continue

        if bullet_buf is not None and line.startswith(" "):
            bullet_buf.append(line)
            continue

        if not line.strip():
            flush_bullet()

    flush_bullet()
    return releases


def find_changelog_path() -> Path | None:
    """Acha o CHANGELOG.md. Primeiro tenta junto ao pyproject (dev/editable);
    cai pra um possível arquivo embarcado em `package-data` futuramente.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "CHANGELOG.md"
        if cand.exists():
            return cand
        if (parent / "pyproject.toml").exists():
            cand = parent / "CHANGELOG.md"
            return cand if cand.exists() else None
    try:
        with resources.as_file(
            resources.files("claude_workspaces").joinpath("CHANGELOG.md")
        ) as p:
            if p.exists():
                return Path(p)
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    return None


def load_releases() -> list[Release]:
    path = find_changelog_path()
    if not path or not path.exists():
        return []
    return parse_changelog(path.read_text(encoding="utf-8"))
