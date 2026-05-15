import json

from claude_workspaces import workspace_templates
from claude_workspaces.workspace_templates import (
    WorkspaceTemplate,
    all_templates,
    bundled,
    load_custom,
)


def test_bundled_has_expected():
    names = {t.name for t in bundled()}
    assert "Vazio" in names
    assert "Java + Spring + PostgreSQL" in names


def test_from_dict_handles_missing_fields():
    t = WorkspaceTemplate.from_dict({})
    assert t.name == "Sem nome"
    assert t.description == ""
    assert t.claude_md == ""
    assert t.tags == []


def test_from_dict_with_full_data():
    t = WorkspaceTemplate.from_dict({
        "name": "Test",
        "description": "Desc",
        "claude_md": "# CLAUDE",
        "tags": ["a", "b"],
    })
    assert t.name == "Test"
    assert t.description == "Desc"
    assert t.claude_md == "# CLAUDE"
    assert t.tags == ["a", "b"]


def test_load_custom_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_templates, "custom_templates_dir", lambda: tmp_path)
    assert load_custom() == []


def test_load_custom_picks_up_jsons(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_templates, "custom_templates_dir", lambda: tmp_path)
    (tmp_path / "team.json").write_text(json.dumps({
        "name": "Team standard",
        "description": "Time A",
    }))
    out = load_custom()
    assert len(out) == 1
    assert out[0].name == "Team standard"


def test_load_custom_skips_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_templates, "custom_templates_dir", lambda: tmp_path)
    (tmp_path / "broken.json").write_text("{ not valid json")
    (tmp_path / "ok.json").write_text(json.dumps({"name": "Ok"}))
    out = load_custom()
    assert [t.name for t in out] == ["Ok"]


def test_all_templates_combines(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_templates, "custom_templates_dir", lambda: tmp_path)
    (tmp_path / "x.json").write_text(json.dumps({"name": "Custom"}))
    names = [t.name for t in all_templates()]
    # bundled first, custom last
    assert names[-1] == "Custom"
    assert "Vazio" in names
