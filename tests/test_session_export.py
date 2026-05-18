import json

from claude_workspaces.services.session_export import (
    _extract_text,
    _format_timestamp,
    export_to_markdown,
)


def test_format_timestamp_empty():
    assert _format_timestamp("") == ""


def test_format_timestamp_iso():
    out = _format_timestamp("2026-05-18T12:30:00Z")
    # Convertido para local TZ — só checamos formato YYYY-MM-DD HH:MM
    assert len(out) == 16
    assert out[4] == "-" and out[7] == "-" and out[10] == " " and out[13] == ":"


def test_format_timestamp_invalid_returns_raw():
    assert _format_timestamp("not-a-date") == "not-a-date"


def test_extract_text_string_passthrough():
    assert _extract_text("hello world") == "hello world"


def test_extract_text_none_returns_empty():
    assert _extract_text(None) == ""


def test_extract_text_text_blocks():
    content = [
        {"type": "text", "text": "primeiro"},
        {"type": "text", "text": "segundo"},
    ]
    assert _extract_text(content) == "primeiro\n\nsegundo"


def test_extract_text_skips_non_dict_entries():
    content = ["string solta", {"type": "text", "text": "ok"}, 42]
    assert _extract_text(content) == "ok"


def test_extract_text_tool_use_with_skill():
    content = [{"type": "tool_use", "name": "Skill", "input": {"skill": "commit"}}]
    assert _extract_text(content) == "_(used Skill · /commit)_"


def test_extract_text_tool_use_with_command():
    content = [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}
    ]
    assert _extract_text(content) == "_(used Bash · ls -la)_"


def test_extract_text_tool_use_command_truncated():
    long_cmd = "x" * 200
    content = [
        {"type": "tool_use", "name": "Bash", "input": {"command": long_cmd}}
    ]
    out = _extract_text(content)
    # Truncado em 80 chars
    assert "x" * 80 in out
    assert "x" * 81 not in out


def test_extract_text_tool_use_without_summary():
    content = [{"type": "tool_use", "name": "Read", "input": {}}]
    assert _extract_text(content) == "_(used Read)_"


def test_extract_text_tool_use_missing_name():
    content = [{"type": "tool_use", "input": {}}]
    assert "?" in _extract_text(content)


def test_extract_text_tool_result_short():
    content = [{"type": "tool_result", "content": "ok"}]
    assert _extract_text(content) == "_(tool result: ok)_"


def test_extract_text_tool_result_long_truncated():
    long_out = "y" * 200
    content = [{"type": "tool_result", "content": long_out}]
    out = _extract_text(content)
    assert "…" in out
    assert "y" * 120 in out
    assert "y" * 121 not in out


def test_extract_text_tool_result_newlines_collapsed():
    content = [{"type": "tool_result", "content": "linha1\nlinha2"}]
    assert _extract_text(content) == "_(tool result: linha1 linha2)_"


def test_extract_text_mixed_blocks():
    content = [
        {"type": "text", "text": "raciocínio"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}},
        {"type": "text", "text": "conclusão"},
    ]
    out = _extract_text(content)
    assert "raciocínio" in out
    assert "_(used Bash · pwd)_" in out
    assert "conclusão" in out


def test_export_file_not_found(tmp_path):
    missing = tmp_path / "nope.jsonl"
    out = export_to_markdown(missing)
    assert out.startswith("# Erro lendo sessão")


def test_export_skips_invalid_json(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        '{not json}\n'
        + json.dumps({
            "type": "user",
            "sessionId": "abc",
            "cwd": "/x",
            "gitBranch": "main",
            "timestamp": "2026-05-18T10:00:00Z",
            "message": {"content": "olá"},
        }) + "\n",
        encoding="utf-8",
    )
    out = export_to_markdown(p)
    assert "olá" in out
    assert "abc" in out


def test_export_full_flow(tmp_path):
    p = tmp_path / "s.jsonl"
    lines = [
        json.dumps({
            "type": "user",
            "sessionId": "sess-1",
            "cwd": "/proj",
            "gitBranch": "main",
            "timestamp": "2026-05-18T10:00:00Z",
            "message": {"content": "qual a cor do céu?"},
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-05-18T10:00:05Z",
            "message": {
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "azul"}],
            },
        }),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = export_to_markdown(p)
    assert "# Sessão Claude" in out
    assert "sess-1" in out
    assert "/proj" in out
    assert "main" in out
    assert "👤 User" in out
    assert "qual a cor do céu?" in out
    assert "🤖 Claude" in out
    assert "`claude-opus-4-7`" in out
    assert "azul" in out


def test_export_skips_empty_text(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        json.dumps({
            "type": "user",
            "sessionId": "x",
            "message": {"content": "   "},
        }) + "\n"
        + json.dumps({
            "type": "user",
            "message": {"content": "real"},
        }) + "\n",
        encoding="utf-8",
    )
    out = export_to_markdown(p)
    assert "real" in out
    # A primeira (só whitespace) é pulada, então só deve ter um header de user
    assert out.count("👤 User") == 1


def test_export_skips_message_without_dict(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        json.dumps({"type": "user", "message": None}) + "\n"
        + json.dumps({"type": "assistant", "message": "not a dict"}) + "\n",
        encoding="utf-8",
    )
    out = export_to_markdown(p)
    # Header existe mas sem conteúdo de mensagens
    assert "# Sessão Claude" in out
    assert "👤 User" not in out
    assert "🤖 Claude" not in out


def test_export_assistant_without_model(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-05-18T10:00:05Z",
            "message": {"content": [{"type": "text", "text": "resposta"}]},
        }) + "\n",
        encoding="utf-8",
    )
    out = export_to_markdown(p)
    assert "🤖 Claude" in out
    assert "resposta" in out
    # Sem backticks ao redor de model quando vazio
    assert "🤖 Claude · " in out or "🤖 Claude\n" in out
