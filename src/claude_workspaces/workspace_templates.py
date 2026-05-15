"""Templates de workspace — pré-popula descrição e/ou CLAUDE.md em
workspaces novos. Bundled in-code + carrega JSONs custom de
~/.config/claude-workspaces/templates/*.json."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class WorkspaceTemplate:
    name: str
    description: str = ""
    claude_md: str = ""  # conteúdo sugerido pra CLAUDE.md do projeto
    tags: list[str] = field(default_factory=list)  # informational

    @classmethod
    def from_dict(cls, d: dict) -> "WorkspaceTemplate":
        return cls(
            name=str(d.get("name") or "").strip() or "Sem nome",
            description=str(d.get("description") or ""),
            claude_md=str(d.get("claude_md") or ""),
            tags=list(d.get("tags") or []),
        )


def _empty() -> WorkspaceTemplate:
    return WorkspaceTemplate(name="Vazio")


def bundled() -> list[WorkspaceTemplate]:
    return [
        _empty(),
        WorkspaceTemplate(
            name="Java + Spring + PostgreSQL",
            description=(
                "Projeto Java/Spring com banco PostgreSQL. Build via "
                "Maven/Gradle, deploy num app server (GlassFish/Tomcat) ou "
                "container."
            ),
            tags=["java", "spring", "postgres"],
            claude_md=(
                "# Convenções deste projeto\n\n"
                "## Stack\n"
                "- Java + Spring (camadas service/repository/controller)\n"
                "- PostgreSQL via JPA/Hibernate\n"
                "- Build: Maven (pom.xml) ou Gradle (build.gradle)\n\n"
                "## Padrões\n"
                "- DTOs separados de entities\n"
                "- Testes com JUnit + Mockito\n"
                "- Logs via SLF4J\n\n"
                "## O que NÃO mexer\n"
                "_(preencha conforme convenções do time)_\n"
            ),
        ),
        WorkspaceTemplate(
            name="Web (Next.js / React)",
            description="App web com Next.js ou Vite + React.",
            tags=["web", "typescript", "react"],
            claude_md=(
                "# Convenções deste projeto\n\n"
                "## Stack\n"
                "- Next.js (App Router) ou Vite + React\n"
                "- TypeScript estrito\n"
                "- Tailwind / CSS modules\n\n"
                "## Padrões\n"
                "- Componentes em PascalCase\n"
                "- Hooks customizados em `hooks/use*.ts`\n"
                "- Testes com Vitest/Testing Library\n"
            ),
        ),
        WorkspaceTemplate(
            name="Python (FastAPI / CLI)",
            description="Projeto Python com FastAPI ou CLI utilitário.",
            tags=["python", "fastapi", "cli"],
            claude_md=(
                "# Convenções deste projeto\n\n"
                "## Stack\n"
                "- Python 3.11+\n"
                "- FastAPI (se web) ou Typer/Click (se CLI)\n"
                "- pytest pra testes\n\n"
                "## Padrões\n"
                "- type hints sempre que possível\n"
                "- pyproject.toml (sem requirements.txt)\n"
                "- Estrutura `src/<pkg>/` + `tests/`\n"
            ),
        ),
    ]


def custom_templates_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces" / "templates"


def load_custom() -> list[WorkspaceTemplate]:
    base = custom_templates_dir()
    if not base.is_dir():
        return []
    out: list[WorkspaceTemplate] = []
    try:
        files = sorted(base.glob("*.json"))
    except OSError:
        return []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Falha lendo template %s: %s", f, e)
            continue
        if isinstance(data, dict):
            out.append(WorkspaceTemplate.from_dict(data))
    return out


def all_templates() -> list[WorkspaceTemplate]:
    return bundled() + load_custom()
