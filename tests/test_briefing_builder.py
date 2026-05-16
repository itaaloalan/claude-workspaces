"""Testes do briefing builder: collect_context, render_briefing,
read_recent_turns."""

import json
from pathlib import Path

from claude_workspaces.briefing_builder import (
    BriefingContext,
    build_briefing,
    render_briefing,
)
from claude_workspaces.claude_sessions import ClaudeSession, read_recent_turns


def _make_session(tmp_path: Path, msgs: list[dict]) -> ClaudeSession:
    path = tmp_path / "abc123-uuid.jsonl"
    with path.open("w", encoding="utf-8") as fp:
        for m in msgs:
            fp.write(json.dumps(m) + "\n")
    return ClaudeSession(
        id="abc123-uuid",
        mtime=path.stat().st_mtime,
        preview="primeiro prompt",
        path=path,
        origin_cwd="/home/x/projeto",
    )


def test_render_briefing_minimo():
    sess = ClaudeSession(
        id="deadbeefdeadbeef",
        mtime=0,
        preview="arrumar o login",
        path=Path("/dev/null"),
        origin_cwd="/home/x/meurepo",
    )
    out = render_briefing(sess, BriefingContext())
    assert "deadbeef" in out
    assert "meurepo" in out
    assert "Tarefa original" in out
    assert "arrumar o login" in out
    assert out.rstrip(" ").endswith("Próximo passo:")


def test_render_briefing_com_git():
    sess = ClaudeSession(
        id="x", mtime=0, preview="", path=Path("/dev/null"), origin_cwd="/p"
    )
    ctx = BriefingContext(
        branch="feat/login",
        ahead=2,
        behind=1,
        changed_files=[("modificado", "src/a.py"), ("novo", "tests/b.py")],
    )
    out = render_briefing(sess, ctx)
    assert "`feat/login`" in out
    assert "↑2" in out
    assert "↓1" in out
    assert "modificado: src/a.py" in out
    assert "novo: tests/b.py" in out


def test_render_briefing_com_turnos():
    sess = ClaudeSession(
        id="x", mtime=0, preview="ignored", path=Path("/dev/null"), origin_cwd="/p"
    )
    ctx = BriefingContext(
        recent_turns=[
            ("user", "implementa autenticação"),
            ("assistant", "vou usar JWT"),
            ("user", "use OAuth ao invés"),
        ]
    )
    out = render_briefing(sess, ctx)
    assert "Últimos turnos" in out
    assert "[Você]" in out
    assert "[Claude]" in out
    assert "implementa autenticação" in out
    assert "use OAuth" in out
    # Quando tem turnos, não usa "Tarefa original" (evita duplicação)
    assert "Tarefa original" not in out


def test_render_briefing_truncates_long_turn():
    sess = ClaudeSession(
        id="x", mtime=0, preview="", path=Path("/dev/null"), origin_cwd="/p"
    )
    long_text = "a" * 2000
    ctx = BriefingContext(recent_turns=[("user", long_text)])
    out = render_briefing(sess, ctx)
    # Tem o "…" do truncate
    assert "…" in out
    # Não bota tudo
    assert "a" * 700 not in out


def test_read_recent_turns_pula_tool_use(tmp_path):
    sess = _make_session(
        tmp_path,
        [
            {"type": "user", "message": {"content": "primeiro"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "ok, vou usar tool"},
                        {"type": "tool_use", "name": "Read", "input": {}},
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "content": "saida"},
                    ]
                },
            },
            {"type": "user", "message": {"content": "agora outra coisa"}},
        ],
    )
    turns = read_recent_turns(sess.path, max_total=10)
    # tool_result devia ter sido pulado (sem campo text)
    assert turns == [
        ("user", "primeiro"),
        ("assistant", "ok, vou usar tool"),
        ("user", "agora outra coisa"),
    ]


def test_read_recent_turns_respeita_max(tmp_path):
    msgs = [
        {"type": "user", "message": {"content": f"msg {i}"}} for i in range(10)
    ]
    sess = _make_session(tmp_path, msgs)
    turns = read_recent_turns(sess.path, max_total=3)
    assert len(turns) == 3
    # Pega os últimos
    assert turns[-1] == ("user", "msg 9")
    assert turns[0] == ("user", "msg 7")


def test_read_recent_turns_arquivo_inexistente(tmp_path):
    turns = read_recent_turns(tmp_path / "nao-existe.jsonl")
    assert turns == []


def test_build_briefing_sem_git(tmp_path):
    sess = _make_session(
        tmp_path,
        [{"type": "user", "message": {"content": "fazer X"}}],
    )
    # primary_folder vazio → sem seção de git
    out = build_briefing(sess, primary_folder="")
    assert "Branch atual" not in out
    assert "fazer X" in out
