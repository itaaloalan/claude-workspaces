"""Testes do services/skills_install."""

from pathlib import Path

import pytest

from claude_workspaces.errors import LaunchError
from claude_workspaces.services.skills_install import (
    SCOPE_PROJECT,
    SCOPE_USER,
    already_installed,
    available_scopes,
    dest_dir,
    install_item,
    target_path,
)
from claude_workspaces.skills_discovery import (
    KIND_AGENT,
    KIND_COMMAND,
    KIND_SKILL,
    ClaudeItem,
)


def _skill(tmp_path: Path, name: str) -> ClaudeItem:
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: x\n---\nbody",
        encoding="utf-8",
    )
    (d / "asset.txt").write_text("asset", encoding="utf-8")
    return ClaudeItem(
        name=name, description="x", source="plugin:foo",
        kind=KIND_SKILL, path=d / "SKILL.md",
    )


def _agent(tmp_path: Path, name: str, source: str = "user") -> ClaudeItem:
    p = tmp_path / f"{name}.md"
    p.write_text(
        f"---\nname: {name}\ndescription: x\n---\nbody",
        encoding="utf-8",
    )
    return ClaudeItem(
        name=name, description="x", source=source, kind=KIND_AGENT, path=p,
    )


def test_dest_dir_user(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert dest_dir(SCOPE_USER, None, KIND_SKILL) == tmp_path / ".claude" / "skills"
    assert dest_dir(SCOPE_USER, None, KIND_AGENT) == tmp_path / ".claude" / "agents"
    assert dest_dir(SCOPE_USER, None, KIND_COMMAND) == tmp_path / ".claude" / "commands"


def test_dest_dir_project(tmp_path):
    ws = str(tmp_path / "proj")
    assert dest_dir(SCOPE_PROJECT, ws, KIND_SKILL) == Path(ws) / ".claude" / "skills"


def test_dest_dir_project_requires_folder():
    with pytest.raises(LaunchError, match="workspace_folder"):
        dest_dir(SCOPE_PROJECT, None, KIND_SKILL)


def test_dest_dir_invalid_scope():
    with pytest.raises(LaunchError, match="escopo"):
        dest_dir("nope", None, KIND_SKILL)


def test_dest_dir_invalid_kind():
    with pytest.raises(LaunchError, match="tipo"):
        dest_dir(SCOPE_USER, None, "garbage")


def test_target_path_skill_uses_subdir(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    item = _skill(src, "my-skill")
    tp = target_path(item, SCOPE_USER)
    assert tp == tmp_path / ".claude" / "skills" / "my-skill" / "SKILL.md"


def test_target_path_agent_is_flat_file(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    item = _agent(tmp_path, "agent-x")
    tp = target_path(item, SCOPE_USER)
    assert tp == tmp_path / ".claude" / "agents" / "agent-x.md"


def test_install_skill_copies_full_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    src = tmp_path / "src"
    src.mkdir()
    item = _skill(src, "fancy")
    result = install_item(item, SCOPE_USER)
    assert result.exists()
    assert (result.parent / "asset.txt").read_text() == "asset"


def test_install_agent_copies_single_file(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    item = _agent(tmp_path, "agent-x", source="plugin:foo")
    result = install_item(item, SCOPE_USER)
    assert result.exists()
    assert "agent-x" in result.read_text()


def test_install_refuses_existing_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    item = _agent(tmp_path, "agent-x", source="plugin:foo")
    install_item(item, SCOPE_USER)
    with pytest.raises(LaunchError, match="já existe"):
        install_item(item, SCOPE_USER)


def test_install_overwrites_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    item = _agent(tmp_path, "agent-x", source="plugin:foo")
    install_item(item, SCOPE_USER)
    # modifica o source
    item.path.write_text(
        "---\nname: agent-x\ndescription: alterado\n---\nnovo body",
        encoding="utf-8",
    )
    new_path = install_item(item, SCOPE_USER, overwrite=True)
    assert "alterado" in new_path.read_text()


def test_install_to_project(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    item = _skill(src, "shared")
    result = install_item(item, SCOPE_PROJECT, workspace_folder=str(proj))
    assert result == proj / ".claude" / "skills" / "shared" / "SKILL.md"


def test_already_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    item = _agent(tmp_path, "ag", source="plugin:foo")
    assert not already_installed(item, SCOPE_USER)
    install_item(item, SCOPE_USER)
    assert already_installed(item, SCOPE_USER)


def test_available_scopes_excludes_origin(tmp_path):
    # Item já é "user" → não oferece SCOPE_USER, só projeto se ws
    item = _agent(tmp_path, "ag", source="user")
    scopes = available_scopes(item, workspace_folder=str(tmp_path))
    assert all(s[0] != SCOPE_USER for s in scopes)
    assert any(s[0] == SCOPE_PROJECT for s in scopes)


def test_available_scopes_no_workspace(tmp_path):
    item = _agent(tmp_path, "ag", source="plugin:foo")
    scopes = available_scopes(item, workspace_folder=None)
    # Só user; projeto omitido (sem ws)
    assert len(scopes) == 1
    assert scopes[0][0] == SCOPE_USER


def test_available_scopes_marks_already_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    item = _agent(tmp_path, "ag", source="plugin:foo")
    install_item(item, SCOPE_USER)
    scopes = available_scopes(item, workspace_folder=None)
    assert any("já instalado" in s[2] for s in scopes)
