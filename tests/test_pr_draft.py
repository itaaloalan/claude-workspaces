"""Testes do builder de PR draft."""

from claude_workspaces.pr_draft import (
    SEP_FIELD,
    SEP_RECORD,
    Commit,
    _parse_log,
    build_draft,
)


def test_build_draft_sem_commits():
    d = build_draft([], fallback_title="feat/login")
    assert d.title == "feat/login"
    assert "Sem commits" in d.body
    assert "Test plan" in d.body


def test_build_draft_sem_commits_sem_fallback():
    d = build_draft([])
    assert "sem commits" in d.title.lower()


def test_build_draft_um_commit_sem_body():
    c = Commit(sha="abc123", subject="feat: adiciona login", body="")
    d = build_draft([c])
    assert d.title == "feat: adiciona login"
    # Body vai ter o subject como resumo quando não há body explícito
    assert "feat: adiciona login" in d.body
    assert "## Test plan" in d.body


def test_build_draft_um_commit_com_body():
    c = Commit(
        sha="abc",
        subject="feat: login",
        body="Adiciona endpoint /login\n\nUsa JWT pra autenticar.",
    )
    d = build_draft([c])
    assert d.title == "feat: login"
    assert "Adiciona endpoint /login" in d.body
    assert "Usa JWT" in d.body


def test_build_draft_n_commits():
    commits = [
        Commit(sha="aaa", subject="feat: parte 1", body=""),
        Commit(sha="bbb", subject="fix: bug X", body=""),
        Commit(sha="ccc", subject="feat: parte 2", body=""),
    ]
    d = build_draft(commits)
    # Título = commit mais recente (último, em ordem cronológica)
    assert d.title == "feat: parte 2"
    # Body lista todos
    assert "- feat: parte 1" in d.body
    assert "- fix: bug X" in d.body
    assert "- feat: parte 2" in d.body
    assert "## Resumo" in d.body
    assert "## Test plan" in d.body


def test_parse_log_vazio():
    assert _parse_log("") == []


def test_parse_log_um_commit():
    raw = f"abc123{SEP_FIELD}feat: x{SEP_FIELD}corpo opcional{SEP_RECORD}"
    commits = _parse_log(raw)
    assert len(commits) == 1
    assert commits[0].sha == "abc123"
    assert commits[0].subject == "feat: x"
    assert commits[0].body == "corpo opcional"


def test_parse_log_pula_chunks_invalidos():
    raw = (
        f"abc{SEP_FIELD}subj1{SEP_RECORD}"
        # chunk sem campo separador → ignorado
        f"naotemcampos{SEP_RECORD}"
        f"def{SEP_FIELD}subj2{SEP_FIELD}{SEP_RECORD}"
    )
    commits = _parse_log(raw)
    assert len(commits) == 2
    assert commits[0].subject == "subj1"
    assert commits[1].subject == "subj2"
