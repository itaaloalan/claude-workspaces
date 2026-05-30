"""Testes de services/changelog.py — parser do CHANGELOG (Keep a Changelog)."""

from claude_workspaces.services import changelog
from claude_workspaces.services.changelog import (
    Release,
    load_releases,
    parse_changelog,
)

# ---------- parse_changelog: headers de versão ----------

def test_parse_bracketed_version():
    rels = parse_changelog("## [1.0.0]\n### Added\n- x")
    assert len(rels) == 1
    assert rels[0].version == "1.0.0"
    assert rels[0].date == ""


def test_parse_version_with_date_emdash():
    rels = parse_changelog("## 1.2.3 — 2025-05-30\n### Fixed\n- y")
    assert rels[0].version == "1.2.3"
    assert rels[0].date == "2025-05-30"


def test_parse_bracketed_version_with_date():
    rels = parse_changelog("## [0.78.0] — 2026-05-30\n### Added\n- z")
    assert rels[0].version == "0.78.0"
    assert rels[0].date == "2026-05-30"


def test_parse_version_no_date():
    rels = parse_changelog("## 0.77.0\n### Added\n- a")
    assert rels[0].version == "0.77.0"
    assert rels[0].date == ""


# ---------- seções e bullets ----------

def test_parse_sections_and_bullets():
    text = (
        "## [1.0.0]\n"
        "### Adicionado\n"
        "- primeiro\n"
        "- segundo\n"
        "### Corrigido\n"
        "* bug fix\n"
    )
    rel = parse_changelog(text)[0]
    assert rel.sections["Adicionado"] == ["primeiro", "segundo"]
    assert rel.sections["Corrigido"] == ["bug fix"]


def test_parse_multiline_bullet_joins():
    text = (
        "## [1.0.0]\n"
        "### Added\n"
        "- linha um\n"
        "  continuação\n"
        "- linha dois\n"
    )
    rel = parse_changelog(text)[0]
    assert rel.sections["Added"] == ["linha um continuação", "linha dois"]


def test_parse_multiple_releases_in_order():
    text = "## [2.0.0]\n### Added\n- novo\n## [1.0.0]\n### Added\n- velho\n"
    rels = parse_changelog(text)
    assert [r.version for r in rels] == ["2.0.0", "1.0.0"]


# ---------- casos vazios / sem header ----------

def test_parse_empty():
    assert parse_changelog("") == []


def test_parse_no_version_header_ignored():
    # Conteúdo antes de qualquer "## versão" é ignorado
    assert parse_changelog("# Changelog\n\nblá blá\n- bullet solto") == []


# ---------- Release.body_markdown ----------

def test_body_markdown_formats_sections():
    rel = Release(version="1.0.0", date="", sections={"Added": ["a", "b"]})
    assert rel.body_markdown == "### Added\n- a\n- b"


def test_body_markdown_multiple_sections():
    rel = Release(
        version="1.0.0",
        date="",
        sections={"Added": ["a"], "Fixed": ["b"]},
    )
    assert rel.body_markdown == "### Added\n- a\n\n### Fixed\n- b"


def test_body_markdown_empty_sections():
    assert Release(version="1.0.0", date="").body_markdown == ""


# ---------- load_releases ----------

def test_load_releases_no_path(monkeypatch):
    monkeypatch.setattr(changelog, "find_changelog_path", lambda: None)
    assert load_releases() == []


def test_load_releases_real_file_has_entries():
    # O CHANGELOG real do repo deve parsear com pelo menos uma release
    rels = load_releases()
    assert isinstance(rels, list)
    assert len(rels) >= 1
    assert all(r.version for r in rels)
