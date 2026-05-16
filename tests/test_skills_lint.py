"""Testes do skills_lint."""

from pathlib import Path

from claude_workspaces.skills_discovery import (
    KIND_AGENT,
    KIND_COMMAND,
    KIND_SKILL,
    ClaudeItem,
)
from claude_workspaces.skills_lint import (
    SEV_ERROR,
    SEV_INFO,
    SEV_WARNING,
    lint_all,
    lint_item,
    summarize_severity,
)


def _make_item(
    tmp_path: Path,
    name: str,
    content: str,
    kind: str = KIND_SKILL,
    layout: str = "subdir",
) -> ClaudeItem:
    if kind == KIND_SKILL and layout == "subdir":
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        path = d / "SKILL.md"
    else:
        path = tmp_path / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return ClaudeItem(
        name=name, description="", source="user", kind=kind, path=path
    )


def test_clean_skill_no_issues(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\ndescription: " + ("descrição longa o bastante pra passar " * 2) + "\n---\n\n"
        + ("body com bastante conteúdo " * 5),
    )
    assert lint_item(item) == []


def test_missing_name_error(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\ndescription: " + ("desc longa o bastante " * 3) + "\n---\n\n"
        + ("body " * 20),
    )
    issues = lint_item(item)
    codes = {i.code for i in issues}
    assert "E001" in codes
    assert any(i.severity == SEV_ERROR for i in issues)


def test_missing_description(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\n---\n\n" + ("body " * 20),
    )
    codes = {i.code for i in lint_item(item)}
    assert "E002" in codes


def test_no_frontmatter(tmp_path):
    item = _make_item(tmp_path, "demo", "sem frontmatter aqui")
    codes = {i.code for i in lint_item(item)}
    assert "E003" in codes


def test_unclosed_frontmatter(tmp_path):
    item = _make_item(tmp_path, "demo", "---\nname: demo\nfica aberto\n")
    codes = {i.code for i in lint_item(item)}
    assert "E003" in codes


def test_name_mismatch_warning(tmp_path):
    """Pasta 'demo' mas frontmatter diz 'outro' → W001."""
    item = _make_item(
        tmp_path, "demo",
        "---\nname: outro\ndescription: " + ("desc longa pra valer " * 3) + "\n---\n\n"
        + ("body " * 20),
    )
    codes = {i.code for i in lint_item(item)}
    assert "W001" in codes


def test_short_description(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\ndescription: curta\n---\n\n" + ("body " * 20),
    )
    codes = {i.code for i in lint_item(item)}
    assert "W002" in codes


def test_long_description_info(tmp_path):
    long_desc = "x" * 1100
    item = _make_item(
        tmp_path, "demo",
        f"---\nname: demo\ndescription: {long_desc}\n---\n\n" + ("body " * 20),
    )
    codes = {i.code for i in lint_item(item)}
    assert "W003" in codes


def test_empty_body(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\ndescription: " + ("desc valida o bastante " * 3) + "\n---\n",
    )
    codes = {i.code for i in lint_item(item)}
    assert "W004" in codes


def test_agent_without_tools_info(tmp_path):
    item = _make_item(
        tmp_path, "agent-x",
        "---\nname: agent-x\ndescription: " + ("desc valida o bastante " * 3) + "\n---\n\n"
        + ("body " * 20),
        kind=KIND_AGENT, layout="flat",
    )
    codes = {i.code for i in lint_item(item)}
    assert "W005" in codes


def test_agent_with_tools_no_w005(tmp_path):
    item = _make_item(
        tmp_path, "agent-x",
        "---\nname: agent-x\ndescription: " + ("desc valida o bastante " * 3)
        + "\ntools: Read, Grep\n---\n\n" + ("body " * 20),
        kind=KIND_AGENT, layout="flat",
    )
    codes = {i.code for i in lint_item(item)}
    assert "W005" not in codes


def test_broken_link_warning(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\ndescription: " + ("desc valida " * 4) + "\n---\n\n"
        + "veja [[nao-existe]] e [[existe]] " + ("body " * 10),
    )
    issues = lint_item(item, catalog_names={"existe"})
    codes = [i.code for i in issues]
    assert codes.count("W006") == 1
    assert "nao-existe" in next(i.message for i in issues if i.code == "W006")


def test_links_skipped_without_catalog(tmp_path):
    item = _make_item(
        tmp_path, "demo",
        "---\nname: demo\ndescription: " + ("desc valida " * 4) + "\n---\n\n"
        + "veja [[qualquer-coisa]] " + ("body " * 10),
    )
    codes = {i.code for i in lint_item(item, catalog_names=None)}
    assert "W006" not in codes


def test_lint_all_skips_clean(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    clean = _make_item(
        a, "ok",
        "---\nname: ok\ndescription: " + ("desc valida " * 4) + "\n---\n\n"
        + ("body " * 20),
    )
    dirty = _make_item(
        b, "bad",
        "---\nname: bad\n---\nx",
    )
    result = lint_all([clean, dirty])
    assert clean.path not in result
    assert dirty.path in result


def test_summarize_severity():
    from claude_workspaces.skills_lint import LintIssue
    assert summarize_severity([]) == ""
    assert summarize_severity([LintIssue("X", SEV_INFO, "y")]) == SEV_INFO
    assert summarize_severity([LintIssue("X", SEV_WARNING, "y")]) == SEV_WARNING
    assert summarize_severity([
        LintIssue("X", SEV_INFO, "y"),
        LintIssue("Y", SEV_ERROR, "z"),
    ]) == SEV_ERROR


def test_command_kind(tmp_path):
    """Commands seguem mesmas regras de skill (mas sem layout subdir)."""
    item = _make_item(
        tmp_path, "cmd",
        "---\nname: cmd\ndescription: " + ("desc valida " * 4) + "\n---\n\n"
        + ("body " * 20),
        kind=KIND_COMMAND, layout="flat",
    )
    assert lint_item(item) == []
