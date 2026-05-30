"""Testes de services/runner_prompt.py — builders puros de prompt."""

from claude_workspaces.models import RunnerConfig, Workspace
from claude_workspaces.services.runner_prompt import (
    build_edit_prompt,
    build_generate_prompt,
    pending_runner_path,
)


def _ws(**kw):
    kw.setdefault("name", "MeuProj")
    kw.setdefault("folders", ["/home/x/proj"])
    return Workspace(**kw)


# ---------- pending_runner_path ----------

def test_pending_runner_path_ends_with_workspace_id():
    ws = _ws()
    p = pending_runner_path(ws)
    assert p.name == f"{ws.id}.json"
    assert p.parent.name == "runner-drafts"


# ---------- build_generate_prompt ----------

def test_generate_includes_name_and_folders():
    ws = _ws(name="API", folders=["/srv/a", "/srv/b"])
    out = build_generate_prompt(ws)
    assert "API" in out
    assert "  - /srv/a" in out
    assert "  - /srv/b" in out


def test_generate_includes_out_path():
    ws = _ws()
    out = build_generate_prompt(ws)
    assert str(pending_runner_path(ws)) in out


def test_generate_hint_block_only_when_present():
    ws = _ws()
    assert "Hint do usuário:" not in build_generate_prompt(ws)
    assert "Hint do usuário: subir na 8080" in build_generate_prompt(
        ws, hint="subir na 8080"
    )


def test_generate_blank_hint_is_ignored():
    ws = _ws()
    assert "Hint do usuário:" not in build_generate_prompt(ws, hint="   ")


def test_generate_spec_ref_default_vs_absolute():
    ws = _ws()
    assert "docs/runners-spec.md" in build_generate_prompt(ws)
    custom = build_generate_prompt(ws, spec_path="/abs/spec.md")
    assert "/abs/spec.md" in custom


def test_generate_no_folders_placeholder():
    ws = _ws(folders=[])
    assert "(sem pastas)" in build_generate_prompt(ws)


# ---------- build_edit_prompt ----------

def _runner():
    return RunnerConfig(
        name="web",
        start_cmd="npm run dev",
        console_session_id="sess-123",
        gen_session_id="gen-1",
        gen_cwd="/tmp/gen",
    )


def test_edit_preserves_runner_name():
    ws, r = _ws(), _runner()
    out = build_edit_prompt(ws, r)
    assert '"web"' in out
    assert "mantenha o mesmo" in out


def test_edit_includes_start_cmd_in_config():
    out = build_edit_prompt(_ws(), _runner())
    assert "npm run dev" in out


def test_edit_excludes_volatile_keys():
    out = build_edit_prompt(_ws(), _runner())
    # As chaves não-portáveis não devem aparecer no JSON da config atual
    for key in ("console_session_id", "gen_session_id", "gen_cwd"):
        assert f'"{key}"' not in out
    assert '"id"' not in out


def test_edit_recent_output_truncated_to_6000():
    big = "Z" * 7000  # sentinela única (não aparece no resto do prompt)
    out = build_edit_prompt(_ws(), _runner(), recent_output=big)
    # Só os últimos 6000 chars entram
    assert out.count("Z") == 6000


def test_edit_no_output_block_when_empty():
    out = build_edit_prompt(_ws(), _runner(), recent_output="  ")
    assert "não tem saída recente" in out


def test_edit_hint_block_conditional():
    ws, r = _ws(), _runner()
    assert "O que o usuário quer ajustar:" not in build_edit_prompt(ws, r)
    assert "trocar porta" in build_edit_prompt(ws, r, hint="trocar porta")
