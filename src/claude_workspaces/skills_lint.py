"""Lint de frontmatter e estrutura de skills/agents/commands.

Detecta problemas comuns que fazem o Claude ignorar o recurso na hora
de decidir invocar uma skill:
- frontmatter ausente ou malformado
- `name`/`description` faltando ou vazios
- nome no frontmatter difere do arquivo/pasta (Claude usa o do frontmatter,
  mas humanos procuram pelo do arquivo)
- description curtinha demais — Claude não consegue julgar relevância
- body vazio — skill sem instruções
- links `[[outra-skill]]` que não existem no catálogo
- agentes sem `tools:` (não é erro, mas é warning útil)

Cada regra tem um code curto pra filtrar / silenciar no futuro.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .skills_discovery import KIND_AGENT, KIND_SKILL, ClaudeItem

SEV_ERROR = "error"
SEV_WARNING = "warning"
SEV_INFO = "info"

_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_FRONT_OPEN = "---"


@dataclass(frozen=True)
class LintIssue:
    code: str
    severity: str
    message: str

    def badge(self) -> str:
        if self.severity == SEV_ERROR:
            return "⛔"
        if self.severity == SEV_WARNING:
            return "⚠"
        return "ℹ"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_frontmatter_raw(text: str) -> tuple[dict[str, str], str, str | None]:
    """Devolve (frontmatter_dict, body, error_or_None).

    Reimplementa parsing aqui pra capturar erros estruturais que o
    skills_discovery silencia.
    """
    if not text.startswith(_FRONT_OPEN):
        return {}, text, "no_frontmatter"
    end = text.find("\n" + _FRONT_OPEN, len(_FRONT_OPEN))
    if end == -1:
        return {}, "", "unclosed_frontmatter"
    fm_raw = text[len(_FRONT_OPEN):end].strip()
    body = text[end + len(_FRONT_OPEN) + 1:].lstrip("\n")
    fm: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        fm[key] = val
    return fm, body, None


def _expected_name(item: ClaudeItem) -> str:
    """Nome esperado baseado no path: skill usa nome da pasta,
    agent/command usa o stem do .md."""
    if item.kind == KIND_SKILL and item.path.name.lower() in {"skill.md"}:
        return item.path.parent.name
    return item.path.stem


def lint_item(item: ClaudeItem, catalog_names: set[str] | None = None) -> list[LintIssue]:
    """Roda todas as regras sobre um item e devolve a lista de issues.

    catalog_names: nomes válidos pra resolver links [[x]]. Se None,
    pula checagem de links quebrados.
    """
    issues: list[LintIssue] = []
    text = _read_text(item.path)
    fm, body, parse_err = _parse_frontmatter_raw(text)

    if parse_err == "no_frontmatter":
        issues.append(LintIssue(
            "E003", SEV_ERROR,
            "arquivo não começa com frontmatter ('---' na primeira linha)",
        ))
        return issues
    if parse_err == "unclosed_frontmatter":
        issues.append(LintIssue(
            "E003", SEV_ERROR,
            "frontmatter não tem fechamento ('---' final)",
        ))
        return issues

    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()

    if not name:
        issues.append(LintIssue("E001", SEV_ERROR, "'name' ausente no frontmatter"))
    if not description:
        issues.append(LintIssue("E002", SEV_ERROR, "'description' ausente no frontmatter"))

    if name:
        expected = _expected_name(item)
        if expected and name.lower() != expected.lower():
            issues.append(LintIssue(
                "W001", SEV_WARNING,
                f"name='{name}' difere do arquivo/pasta '{expected}'",
            ))

    if description:
        if len(description) < 30:
            issues.append(LintIssue(
                "W002", SEV_WARNING,
                f"description muito curta ({len(description)} chars) — "
                "Claude não consegue julgar relevância",
            ))
        elif len(description) > 1000:
            issues.append(LintIssue(
                "W003", SEV_INFO,
                f"description muito longa ({len(description)} chars) — "
                "considere mover detalhes pro body",
            ))

    body_stripped = body.strip()
    if len(body_stripped) < 50:
        issues.append(LintIssue(
            "W004", SEV_WARNING,
            "body vazio ou quase vazio — sem instruções pro Claude",
        ))

    if item.kind == KIND_AGENT and "tools" not in fm:
        issues.append(LintIssue(
            "W005", SEV_INFO,
            "agente sem 'tools:' — herda todas as tools do parent",
        ))

    if catalog_names and body_stripped:
        for match in _LINK_RE.finditer(body_stripped):
            target = match.group(1).strip()
            if target and target not in catalog_names:
                issues.append(LintIssue(
                    "W006", SEV_WARNING,
                    f"link [[{target}]] aponta pra recurso inexistente",
                ))

    return issues


def lint_all(items: list[ClaudeItem]) -> dict[Path, list[LintIssue]]:
    """Roda lint em todos os itens devolvendo {path: [issues]}.

    Itens sem issues não aparecem no dict (caller usa get(path, [])).
    """
    catalog_names = {i.name for i in items}
    out: dict[Path, list[LintIssue]] = {}
    for item in items:
        issues = lint_item(item, catalog_names)
        if issues:
            out[item.path] = issues
    return out


def summarize_severity(issues: list[LintIssue]) -> str:
    """Pior severidade ou string vazia. Ordem: error > warning > info."""
    if any(i.severity == SEV_ERROR for i in issues):
        return SEV_ERROR
    if any(i.severity == SEV_WARNING for i in issues):
        return SEV_WARNING
    if issues:
        return SEV_INFO
    return ""
