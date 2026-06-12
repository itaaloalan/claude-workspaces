"""Testes do naming auto-derivado de branch e da estabilização do claim.

Regressão do bug em que, com vários consoles no MESMO project-dir (lançados
no mesmo cwd e criando worktrees em runtime via /criar-worktree), uma sessão
nova ficava com o NOME de outra: o chip de worktree corrigia pro worktree
certo, mas o título ficava congelado no branch do worktree errado.
"""

import pytest

from claude_workspaces.claude_sessions import BackendSession
from claude_workspaces.ui.terminal_widget import TerminalWidget


@pytest.fixture
def widget(qapp, tmp_workspaces):
    # tmp_workspaces redireciona config_dir → session_marks.json vai pro tmp.
    return TerminalWidget()


def test_auto_name_follows_adopted_worktree(widget):
    """Nome auto-derivado de branch acompanha a TROCA de worktree — chip e
    título nunca desincronizam."""
    widget._maybe_name_after_branch("feat/tarja-ambiente-desenvolvimento")
    assert widget._custom_name == "feat: tarja ambiente desenvolvimento"
    assert widget._name_from_branch is True

    # Console passa a adotar OUTRO worktree: o nome auto deve seguir.
    widget._maybe_name_after_branch("fix/erro-de-sincronizacao-de-ocorrencias")
    assert widget._custom_name == "fix: erro de sincronizacao de ocorrencias"
    assert widget._name_from_branch is True


def test_user_name_is_never_overwritten_by_branch(widget):
    """Nome posto pelo usuário (set_custom_name) tem precedência e não é
    sobrescrito quando o console adota/troca de worktree."""
    widget.set_custom_name("Meu nome manual")
    assert widget._name_from_branch is False

    widget._maybe_name_after_branch("feat/tarja-ambiente-desenvolvimento")
    assert widget._custom_name == "Meu nome manual"
    assert widget._name_from_branch is False


def test_set_custom_name_clears_branch_flag_after_auto(widget):
    """Depois de um nome auto, um rename manual reassume controle: o nome
    para de seguir o worktree."""
    widget._maybe_name_after_branch("feat/tarja-ambiente-desenvolvimento")
    assert widget._name_from_branch is True

    widget.set_custom_name("Renomeado pelo usuário")
    assert widget._name_from_branch is False

    widget._maybe_name_after_branch("fix/outro-branch-qualquer")
    assert widget._custom_name == "Renomeado pelo usuário"


def _sess(sid, preview, mtime):
    return BackendSession(
        id=sid, mtime=mtime, preview=preview, path="/x", origin_cwd="/x"
    )


def test_resolve_sticks_to_claimed_session_until_preview(widget, monkeypatch):
    """Claim já feito sem preview: o widget re-lê o preview DESSE id em vez
    de pular pra outra sessão (evita o claim churn que escaneava o JSONL de
    outro console no mesmo dir)."""
    import claude_workspaces.claude_sessions as cs

    widget._claude_cwd = "/x"
    widget._claude_resume_id = None
    widget._claude_start_time = 1000.0
    widget._session_resolved = False
    widget._claimed_session_id = "A"

    # "A" ainda sem preview; "B" (de outro console) já tem preview e mtime
    # próximo do nosso start — sem o fix, o widget pularia pra "B".
    sessions = [
        _sess("A", "", 1001.0),
        _sess("B", "feat: tarja ambiente desenvolvimento", 1000.5),
    ]
    monkeypatch.setattr(
        cs, "list_sessions_backend", lambda *a, **k: sessions
    )
    widget._try_resolve_session()
    assert widget._claimed_session_id == "A"
    assert widget._session_resolved is False
    assert not widget._session_preview

    # Quando "A" finalmente ganha preview, resolve nele (não em "B").
    sessions[0] = _sess("A", "minha tarefa de verdade", 1002.0)
    widget._try_resolve_session()
    assert widget._claimed_session_id == "A"
    assert widget._session_resolved is True
    assert widget._session_preview == "minha tarefa de verdade"
