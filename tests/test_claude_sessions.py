"""Testes do módulo claude_sessions — parsing dos JSONLs do Claude Code.

Foca em: extração de texto de blocos heterogêneos, leitura defensiva
(arquivos quebrados, linhas inválidas), label() formatting, encoding
do project_path."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from claude_workspaces.claude_sessions import (
    ClaudeSession,
    _encode_project_path,
    _extract_text,
    _read_first_user_message,
    find_session_file,
    list_sessions,
    list_sessions_for_paths,
    project_sessions_dir,
    read_recent_turns,
)


def test_encode_project_path_simple():
    assert _encode_project_path("/home/user/proj") == "-home-user-proj"


def test_encode_project_path_with_spaces_underscores_dots():
    assert (
        _encode_project_path("/home/italo/Projetos/SIPE Sistemas/ponto_python_antigo/api")
        == "-home-italo-Projetos-SIPE-Sistemas-ponto-python-antigo-api"
    )
    assert _encode_project_path("/home/italo/.local/share/x") == "-home-italo--local-share-x"


def test_project_sessions_dir_under_home():
    out = project_sessions_dir("/abs/path")
    assert ".claude/projects" in str(out)
    assert out.name == "-abs-path"


def test_extract_text_from_string():
    assert _extract_text("hello world") == "hello world"
    assert _extract_text("  trimmed  ") == "trimmed"


def test_extract_text_from_block_list():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "tool_use", "name": "ignored"},
        {"type": "text", "text": "second"},
    ]
    assert _extract_text(blocks) == "first\nsecond"


def test_extract_text_skips_tool_results():
    blocks = [
        {"type": "tool_result", "content": "should not appear"},
        {"type": "image", "url": "skip"},
    ]
    assert _extract_text(blocks) == ""


def test_extract_text_handles_missing_keys():
    blocks = [{"type": "text"}]  # sem field text
    assert _extract_text(blocks) == ""


def _write_session(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for e in events:
            fp.write(json.dumps(e) + "\n")


def test_read_first_user_message_picks_first_with_text(tmp_path):
    f = tmp_path / "session.jsonl"
    _write_session(
        f,
        [
            {"type": "system", "message": {"content": "ignored"}},
            {"type": "user", "message": {"content": "primeira mensagem"}},
            {"type": "user", "message": {"content": "segunda"}},
        ],
    )
    assert _read_first_user_message(f) == "primeira mensagem"


def test_read_first_user_message_skips_malformed_lines(tmp_path):
    f = tmp_path / "session.jsonl"
    with f.open("w", encoding="utf-8") as fp:
        fp.write("não-json\n")
        fp.write(json.dumps({"type": "user", "message": {"content": "real"}}) + "\n")
    assert _read_first_user_message(f) == "real"


def test_read_first_user_message_returns_empty_on_missing(tmp_path):
    assert _read_first_user_message(tmp_path / "doesnotexist.jsonl") == ""


def test_read_first_user_message_skips_blocks_without_text(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_session(
        f,
        [
            {"type": "user", "message": {"content": [{"type": "tool_use"}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "ok"}]}},
        ],
    )
    assert _read_first_user_message(f) == "ok"


def test_read_recent_turns_keeps_only_text_and_caps(tmp_path):
    f = tmp_path / "s.jsonl"
    events = []
    for i in range(10):
        events.append({"type": "user", "message": {"content": f"u{i}"}})
        events.append({"type": "assistant", "message": {"content": f"a{i}"}})
    _write_session(f, events)
    out = read_recent_turns(f, max_total=4)
    assert len(out) == 4
    assert out[-1] == ("assistant", "a9")
    assert out[-2] == ("user", "u9")


def test_read_recent_turns_missing_file_returns_empty(tmp_path):
    assert read_recent_turns(tmp_path / "noo.jsonl") == []


def test_list_sessions_empty_when_dir_missing(tmp_path):
    # project_sessions_dir aponta pra ~/.claude/projects/... — irrelevante
    # pro teste; só importa que não-existe → []
    assert list_sessions(str(tmp_path / "ghost-path")) == []


def test_list_sessions_for_paths_dedups_and_orders(tmp_path, monkeypatch):
    # Cria duas project dirs falsas com .jsonl com mtimes diferentes
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    proj_a = "/repo/a"
    proj_b = "/repo/b"
    dir_a = project_sessions_dir(proj_a)
    dir_b = project_sessions_dir(proj_b)
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    old = dir_a / "old.jsonl"
    new = dir_b / "new.jsonl"
    _write_session(old, [{"type": "user", "message": {"content": "old prompt"}}])
    _write_session(new, [{"type": "user", "message": {"content": "new prompt"}}])
    # mtime: old < new
    past = time.time() - 3600
    import os
    os.utime(old, (past, past))

    out = list_sessions_for_paths([proj_a, proj_b], limit=10)
    assert len(out) == 2
    # Mais recente primeiro
    assert out[0].path == new
    assert out[1].path == old


def test_find_session_file_locates_across_projects(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    dir_a = project_sessions_dir("/repo/a")
    dir_b = project_sessions_dir("/repo/b")
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    target = dir_b / "abc-123.jsonl"
    _write_session(target, [{"type": "user", "message": {"content": "oi"}}])

    assert find_session_file("abc-123") == target


def test_find_session_file_returns_none_when_missing(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert find_session_file("nope") is None
    assert find_session_file("") is None


def test_claude_session_label_today_includes_hour():
    s = ClaudeSession(
        id="abc",
        mtime=datetime.now().timestamp(),
        preview="hello world",
        path=Path("/tmp/x.jsonl"),
        origin_cwd="/tmp",
    )
    lbl = s.label()
    assert "hoje" in lbl
    assert "hello world" in lbl


def test_claude_session_label_yesterday():
    yesterday = datetime.now() - timedelta(days=1)
    s = ClaudeSession(
        id="abc",
        mtime=yesterday.timestamp(),
        preview="prompt antigo",
        path=Path("/tmp/x.jsonl"),
        origin_cwd="/tmp",
    )
    assert "ontem" in s.label()


def test_claude_session_label_no_preview():
    s = ClaudeSession(
        id="abc",
        mtime=datetime.now().timestamp(),
        preview="",
        path=Path("/tmp/x.jsonl"),
        origin_cwd="/tmp",
    )
    assert "(sem prompt registrado)" in s.label()


def test_claude_session_label_truncates_long_preview():
    s = ClaudeSession(
        id="abc",
        mtime=datetime.now().timestamp(),
        preview="A" * 200,
        path=Path("/tmp/x.jsonl"),
        origin_cwd="/tmp",
    )
    lbl = s.label(max_preview=20)
    # Tem o ellipsis na linha
    assert "…" in lbl


def test_claude_session_label_with_origin():
    s = ClaudeSession(
        id="abc",
        mtime=datetime.now().timestamp(),
        preview="oi",
        path=Path("/tmp/x.jsonl"),
        origin_cwd="/home/user/my-project",
    )
    assert "[my-project]" in s.label(include_origin=True)


# ------------------------------------------------------- scan_worktree_adds


def _bash_line(command: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": command},
            }],
        },
    })


def test_scan_worktree_adds_detects_skill_style(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _bash_line('git worktree add "/repo.claude/ws_feat_x" -b "feat/x" "origin/develop"')
        + "\n",
        encoding="utf-8",
    )
    hits, offset = scan_worktree_adds(f, 0)
    assert hits == [("/repo.claude/ws_feat_x", "feat/x", "origin/develop")]
    assert offset == f.stat().st_size


def test_scan_worktree_adds_detects_b_before_path(tmp_path: Path):
    # Ordem usada pelo git_worktree.add_worktree: add -b <branch> <path> <base>
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _bash_line("git worktree add -b claude/123 /tmp/wt main") + "\n",
        encoding="utf-8",
    )
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == [("/tmp/wt", "claude/123", "main")]


def test_scan_worktree_adds_detects_move(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _bash_line(
            'git -C /repo worktree move "/repo.claude/ws_fix_old" "/repo.claude/ws_fix_new"'
        )
        + "\n",
        encoding="utf-8",
    )
    hits, offset = scan_worktree_adds(f, 0)
    assert hits == [("/repo.claude/ws_fix_new", "", "")]
    assert offset == f.stat().st_size


def test_scan_worktree_adds_move_com_um_positional_ignora(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _bash_line("git worktree move /repo.claude/so_um") + "\n",
        encoding="utf-8",
    )
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == []


def _tool_result_line(text: str) -> str:
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_x",
                "content": text,
            }],
        },
    })


def test_scan_worktree_adds_detects_enter_worktree_result(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _tool_result_line(
            "Entered worktree at /repo.claude/ws_feat_x on branch feat/x. "
            "The session is now working in the worktree."
        )
        + "\n",
        encoding="utf-8",
    )
    hits, offset = scan_worktree_adds(f, 0)
    assert hits == [("/repo.claude/ws_feat_x", "feat/x", "")]
    assert offset == f.stat().st_size


def test_scan_worktree_adds_enter_worktree_result_em_lista(tmp_path: Path):
    # content do tool_result também pode vir como lista de blocos text.
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    line = json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_x",
                "content": [{
                    "type": "text",
                    "text": "Entered worktree at /tmp/wt3 on branch fix/z. Use ExitWorktree to leave.",
                }],
            }],
        },
    })
    f.write_text(line + "\n", encoding="utf-8")
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == [("/tmp/wt3", "fix/z", "")]


def test_scan_worktree_adds_bash_com_variavel_nao_explode(tmp_path: Path):
    # Path em variável shell: gera hit "$WT" (caller descarta na validação).
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(
        _bash_line('git worktree add "$WT" "italo/api_dados_xml"') + "\n",
        encoding="utf-8",
    )
    # Sem -b, o 2º posicional cai em base; o caller descarta o hit (path "$WT").
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == [("$WT", "", "italo/api_dados_xml")]


def test_scan_worktree_adds_incremental_offset(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    f.write_text(_bash_line("ls -la") + "\n", encoding="utf-8")
    hits, offset = scan_worktree_adds(f, 0)
    assert hits == []
    # Nova linha com worktree add: só ela é lida a partir do offset.
    with f.open("a", encoding="utf-8") as fp:
        fp.write(_bash_line('git worktree add "/tmp/wt2" -b "fix/y"') + "\n")
    hits, offset2 = scan_worktree_adds(f, offset)
    assert hits == [("/tmp/wt2", "fix/y", "")]
    assert offset2 > offset
    # Re-scan no offset final: nada novo.
    hits, _ = scan_worktree_adds(f, offset2)
    assert hits == []


def test_scan_worktree_adds_ignores_partial_line(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    full = _bash_line('git worktree add "/tmp/wt3"') + "\n"
    partial = full[: len(full) // 2]  # sessão ainda escrevendo
    f.write_text(partial, encoding="utf-8")
    hits, offset = scan_worktree_adds(f, 0)
    assert hits == [] and offset == 0
    # Completa a linha → próximo scan pega.
    f.write_text(full, encoding="utf-8")
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == [("/tmp/wt3", "", "")]


def test_scan_worktree_adds_ignores_non_bash_mentions(tmp_path: Path):
    from claude_workspaces.claude_sessions import scan_worktree_adds
    f = tmp_path / "s.jsonl"
    # Texto de assistant falando sobre worktree add (não é tool_use Bash).
    line = json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "vou rodar git worktree add em /x"}],
        },
    })
    f.write_text(line + "\n", encoding="utf-8")
    hits, _ = scan_worktree_adds(f, 0)
    assert hits == []
