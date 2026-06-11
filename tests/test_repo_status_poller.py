"""Testes do RepoStatusPoller — emite GitStatus completo com cache TTL.

Mocka `get_status` (referência importada no módulo do poller) pra não
depender de git/disco; processa eventos do Qt até o signal chegar.
"""

import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from claude_workspaces.git_status import GitFile, GitStatus
from claude_workspaces.repo_status_poller import RepoStatusPoller


def _wait_for(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _status(folder: str) -> GitStatus:
    return GitStatus(
        folder=folder,
        is_repo=True,
        branch="feat/x",
        ahead=2,
        behind=1,
        files=[GitFile(status=" M", path="a.py"), GitFile(status="??", path="b.txt")],
    )


def test_emite_git_status_completo(qapp):
    got = []
    poller = RepoStatusPoller(ttl_seconds=60.0)
    poller.status_ready.connect(lambda folder, st: got.append((folder, st)))
    with patch(
        "claude_workspaces.repo_status_poller.get_status",
        side_effect=_status,
    ):
        poller.request("/repo")
        assert _wait_for(lambda: got)
    folder, st = got[0]
    assert folder == "/repo"
    assert isinstance(st, GitStatus)
    assert st.branch == "feat/x"
    assert st.ahead == 2
    assert st.behind == 1
    assert len(st.files) == 2


def test_cache_fresco_emite_sem_novo_fetch(qapp):
    got = []
    calls = []
    poller = RepoStatusPoller(ttl_seconds=60.0)
    poller.status_ready.connect(lambda folder, st: got.append(st))

    def _spy(folder):
        calls.append(folder)
        return _status(folder)

    with patch("claude_workspaces.repo_status_poller.get_status", side_effect=_spy):
        poller.request("/repo")
        assert _wait_for(lambda: got)
        # 2ª chamada com cache fresco: emite na hora, sem novo get_status.
        poller.request("/repo")
        assert _wait_for(lambda: len(got) >= 2)
    assert calls == ["/repo"]
    assert got[1].branch == "feat/x"


def test_nao_repo_emite_status_sintetico(qapp):
    got = []
    poller = RepoStatusPoller(ttl_seconds=60.0)
    poller.status_ready.connect(lambda folder, st: got.append(st))
    with patch(
        "claude_workspaces.repo_status_poller.get_status",
        return_value=GitStatus(folder="/nao-repo", is_repo=False),
    ):
        poller.request("/nao-repo")
        assert _wait_for(lambda: got)
    st = got[0]
    assert st.is_repo is False
    assert st.branch == ""
    assert st.files == []
