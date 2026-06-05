"""Testes do clean_session_text — títulos de sessão iniciada por slash
command não podem exibir as tags <command-*> cruas na sidebar."""

import json

from claude_workspaces.claude_sessions import (
    _read_first_user_message,
    clean_session_text,
)


def test_slash_command_vira_nome_legivel():
    raw = (
        "<command-message>criar-worktree</command-message>"
        "<command-name>/criar-worktree</command-name>"
    )
    assert clean_session_text(raw) == "/criar-worktree"


def test_slash_command_com_args():
    raw = (
        "<command-message>rodar-runner</command-message>"
        "<command-name>/rodar-runner</command-name>"
        "<command-args>web</command-args>"
    )
    assert clean_session_text(raw) == "/rodar-runner web"


def test_texto_normal_passa_intacto():
    assert clean_session_text("corrige o bug do runner") == (
        "corrige o bug do runner"
    )
    # `<` legítimo em texto comum não é mexido.
    assert clean_session_text("compare a < b no loop") == "compare a < b no loop"


def test_stdout_de_comando_local_sem_tags():
    raw = "<local-command-stdout>saída do comando</local-command-stdout>"
    assert clean_session_text(raw) == "saída do comando"


def test_first_user_message_limpa_tags(tmp_path):
    jsonl = tmp_path / "sess.jsonl"
    lines = [
        {"type": "summary", "summary": "x"},
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": (
                    "<command-message>criar-worktree</command-message>"
                    "<command-name>/criar-worktree</command-name>"
                ),
            },
        },
    ]
    jsonl.write_text("\n".join(json.dumps(ln) for ln in lines), encoding="utf-8")
    assert _read_first_user_message(jsonl) == "/criar-worktree"


# ---- branch_to_session_name -------------------------------------------------


def test_branch_to_session_name():
    from claude_workspaces.ui.terminal_widget import branch_to_session_name

    assert branch_to_session_name("fix/extrair-informacoes-lacres") == (
        "fix: extrair informacoes lacres"
    )
    assert branch_to_session_name("feat/campo_poco_secundario") == (
        "feat: campo poco secundario"
    )
    assert branch_to_session_name(" · feat/x-y") == "feat: x y"
    assert branch_to_session_name("develop") == "develop"
    assert branch_to_session_name("") == ""
    assert branch_to_session_name("isolado") == ""
