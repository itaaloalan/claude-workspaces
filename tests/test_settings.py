from claude_workspaces import settings as settings_mod
from claude_workspaces.settings import Settings


def test_defaults():
    s = Settings()
    assert s.claude_command == "claude"
    assert s.terminal_command == "konsole"
    assert s.body_splitter_sizes == []
    assert s.right_splitter_sizes == []
    assert s.window_geometry == []


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "config_dir", lambda: tmp_path)
    s = Settings(
        claude_command="ia",
        claude_extra_args=["--dangerously-skip-permissions"],
        body_splitter_sizes=[200, 800],
        window_geometry=[100, 50, 1400, 900],
    )
    s.save()
    loaded = Settings.load()
    assert loaded.claude_command == "ia"
    assert loaded.claude_extra_args == ["--dangerously-skip-permissions"]
    assert loaded.body_splitter_sizes == [200, 800]
    assert loaded.window_geometry == [100, 50, 1400, 900]


def test_load_ignores_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"claude_command": "x", "unknown_garbage_field": 42}'
    )
    s = Settings.load()
    assert s.claude_command == "x"


def test_ide_command_lookup():
    s = Settings(intellij_command="idea-ce")
    assert s.ide_command("intellij") == "idea-ce"
    assert s.ide_command("vscode") == "code"
    assert s.ide_command("unknown") == ""
