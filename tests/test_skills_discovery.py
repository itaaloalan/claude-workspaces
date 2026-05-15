from pathlib import Path

from claude_workspaces.skills_discovery import (
    KIND_AGENT,
    KIND_SKILL,
    _list_flat_in,
    _list_skills_in,
    _parse_frontmatter,
    list_all_items,
)


def test_parse_frontmatter_basic():
    text = '---\nname: foo\ndescription: bar baz\n---\n\nbody'
    fm = _parse_frontmatter(text)
    assert fm["name"] == "foo"
    assert fm["description"] == "bar baz"


def test_parse_frontmatter_strips_quotes():
    text = '---\nname: "quoted"\ndescription: \'single\'\n---\n'
    fm = _parse_frontmatter(text)
    assert fm["name"] == "quoted"
    assert fm["description"] == "single"


def test_parse_frontmatter_no_frontmatter():
    assert _parse_frontmatter("just text") == {}


def test_parse_frontmatter_unterminated():
    """Frontmatter sem fechar (sem ---) volta vazio."""
    assert _parse_frontmatter("---\nname: foo\n") == {}


def test_list_skills_subdir_layout(tmp_path):
    (tmp_path / "my-skill").mkdir()
    (tmp_path / "my-skill" / "SKILL.md").write_text(
        '---\nname: my-skill\ndescription: does X\n---\nbody'
    )
    out = _list_skills_in(tmp_path, "user")
    assert len(out) == 1
    assert out[0].name == "my-skill"
    assert out[0].description == "does X"
    assert out[0].kind == KIND_SKILL


def test_list_skills_uses_dir_name_when_no_name_in_md(tmp_path):
    (tmp_path / "subskill").mkdir()
    (tmp_path / "subskill" / "SKILL.md").write_text("no frontmatter here")
    out = _list_skills_in(tmp_path, "user")
    assert len(out) == 1
    assert out[0].name == "subskill"


def test_list_flat_for_agents_commands(tmp_path):
    (tmp_path / "agent1.md").write_text(
        '---\nname: my-agent\ndescription: agent X\n---\nbody'
    )
    (tmp_path / "README.md").write_text("ignore me")
    out = _list_flat_in(tmp_path, "user", KIND_AGENT)
    assert len(out) == 1
    assert out[0].name == "my-agent"
    assert out[0].kind == KIND_AGENT


def test_list_all_items_dedup_priority(tmp_path, monkeypatch):
    """user > plugin pra mesmo (kind, name)."""
    plugin_dir = tmp_path / ".claude" / "plugins" / "marketplaces" / "m" / "plugins" / "p" / "skills"
    user_dir = tmp_path / ".claude" / "skills"
    plugin_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (plugin_dir / "x").mkdir()
    (plugin_dir / "x" / "SKILL.md").write_text(
        '---\nname: x\ndescription: from-plugin\n---'
    )
    (user_dir / "x").mkdir()
    (user_dir / "x" / "SKILL.md").write_text(
        '---\nname: x\ndescription: from-user\n---'
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    items = list_all_items(None)
    skills_x = [i for i in items if i.kind == KIND_SKILL and i.name == "x"]
    assert len(skills_x) == 1
    assert skills_x[0].description == "from-user"
    assert skills_x[0].source == "user"


def test_list_all_items_project_overrides_user(tmp_path, monkeypatch):
    user_dir = tmp_path / ".claude" / "skills"
    user_dir.mkdir(parents=True)
    (user_dir / "x").mkdir()
    (user_dir / "x" / "SKILL.md").write_text(
        '---\nname: x\ndescription: from-user\n---'
    )

    project = tmp_path / "myproj"
    proj_skills = project / ".claude" / "skills"
    proj_skills.mkdir(parents=True)
    (proj_skills / "x").mkdir()
    (proj_skills / "x" / "SKILL.md").write_text(
        '---\nname: x\ndescription: from-project\n---'
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    items = list_all_items([str(project)])
    skills_x = [i for i in items if i.kind == KIND_SKILL and i.name == "x"]
    assert len(skills_x) == 1
    assert skills_x[0].source == "project"
    assert skills_x[0].description == "from-project"


def test_empty_workspace_folders():
    """Não deve crashar quando workspace_folders é None/vazio."""
    out = list_all_items(None)
    # Pode haver itens do user real, mas a função não deve quebrar
    assert isinstance(out, list)
