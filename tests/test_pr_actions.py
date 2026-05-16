"""Testes do pr_actions.find_existing_pr + _extract_pr_url.
Mocka subprocess.run pra evitar dependência do gh CLI nos testes."""

import subprocess
from unittest.mock import patch

from claude_workspaces.pr_actions import (
    ExistingPR,
    _extract_pr_url,
    find_existing_pr,
)


def _fake_completed(rc: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout=stdout, stderr=stderr
    )


def test_extract_pr_url_pega_https():
    out = "Some message\nhttps://github.com/owner/repo/pull/42\n"
    assert _extract_pr_url(out) == "https://github.com/owner/repo/pull/42"


def test_extract_pr_url_pega_ultima_quando_varias():
    out = (
        "https://github.com/old/old/pull/1\n"
        "extra text\n"
        "https://github.com/owner/repo/pull/42\n"
    )
    assert _extract_pr_url(out) == "https://github.com/owner/repo/pull/42"


def test_extract_pr_url_vazio():
    assert _extract_pr_url("") == ""
    assert _extract_pr_url("no url here") == ""


def test_find_existing_pr_gh_indisponivel():
    with patch("claude_workspaces.pr_actions.gh_available", return_value=False):
        assert find_existing_pr("/some/folder", "feat/x") is None


def test_find_existing_pr_open():
    payload = '{"url":"https://github.com/o/r/pull/42","state":"OPEN","number":42}'
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", return_value=_fake_completed(0, stdout=payload)):
        result = find_existing_pr("/folder", "feat/x")
    assert result == ExistingPR(
        url="https://github.com/o/r/pull/42", state="OPEN", number=42
    )


def test_find_existing_pr_merged():
    payload = '{"url":"https://github.com/o/r/pull/10","state":"MERGED","number":10}'
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", return_value=_fake_completed(0, stdout=payload)):
        result = find_existing_pr("/folder", "feat/x")
    assert result is not None
    assert result.state == "MERGED"


def test_find_existing_pr_nenhum():
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", return_value=_fake_completed(1, stderr="no pull requests found")):
        assert find_existing_pr("/folder", "feat/x") is None


def test_find_existing_pr_json_invalido():
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", return_value=_fake_completed(0, stdout="not json")):
        assert find_existing_pr("/folder", "feat/x") is None


def test_find_existing_pr_url_vazia():
    payload = '{"url":"","state":"OPEN","number":1}'
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", return_value=_fake_completed(0, stdout=payload)):
        assert find_existing_pr("/folder", "feat/x") is None


def test_find_existing_pr_timeout():
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=15)):
        assert find_existing_pr("/folder", "feat/x") is None


def test_find_existing_pr_gh_nao_encontrado():
    with patch("claude_workspaces.pr_actions.gh_available", return_value=True), \
         patch("subprocess.run", side_effect=FileNotFoundError("gh")):
        assert find_existing_pr("/folder", "feat/x") is None
