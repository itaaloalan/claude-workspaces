"""Testes do PtySession — foca em comportamento sem fazer fork real
(testes de fork são frágeis em CI). Cobrimos: write/resize com fd
ausente, terminate idempotente, _on_readable EOF, pending_size.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from claude_workspaces.pty_session import PtySession


@pytest.fixture
def session(qapp) -> PtySession:
    return PtySession()


def test_initial_state(session):
    assert session.pid is None
    assert session.master_fd is None
    assert session.is_running() is False


def test_write_without_fd_silently_noops(session):
    # Não levanta — apenas retorna
    session.write(b"hello")


def test_resize_without_fd_stores_pending_size(session):
    session.resize(120, 40)
    assert session._pending_size == (120, 40)


def test_resize_ignores_invalid_dims(session):
    session.resize(0, 0)
    assert session._pending_size is None
    session.resize(-10, 5)
    assert session._pending_size is None


def test_terminate_without_pid_safe(session):
    session.terminate()  # não levanta
    assert session.pid is None


def test_on_readable_emits_finished_on_eof(session):
    """Quando os.read devolve b'' → emite finished e limpa estado."""
    emitted = []
    session.finished.connect(lambda: emitted.append(True))
    session.master_fd = 999  # qualquer valor não-None
    session.pid = 12345
    with patch("claude_workspaces.pty_session.os.read", return_value=b""):
        session._on_readable()
    assert emitted == [True]
    assert session.pid is None
    assert session.master_fd is None


def test_on_readable_emits_data(session):
    """Bytes lidos viram signal output_received."""
    received = []
    session.output_received.connect(lambda b: received.append(b))
    session.master_fd = 999
    session.pid = 12345
    with patch("claude_workspaces.pty_session.os.read", return_value=b"hello"):
        session._on_readable()
    assert received == [b"hello"]
    # Ainda rodando
    assert session.pid == 12345


def test_on_readable_swallows_blocking_io(session):
    """BlockingIOError não derruba o handler — só não emite nada."""
    emitted = []
    session.output_received.connect(lambda b: emitted.append(b))
    session.finished.connect(lambda: emitted.append("FIN"))
    session.master_fd = 999
    session.pid = 12345

    def raise_blocking(_fd, _n):
        raise BlockingIOError()

    with patch("claude_workspaces.pty_session.os.read", side_effect=raise_blocking):
        session._on_readable()
    # data vira b"", o que entra no caminho EOF → finished
    assert "FIN" in emitted


def test_write_swallows_os_error(session):
    session.master_fd = 999

    def raise_os_error(_fd, _data):
        raise OSError("broken")

    with patch("claude_workspaces.pty_session.os.write", side_effect=raise_os_error):
        # Não levanta
        session.write(b"x")


def test_finished_with_status_emits_exit_code(session):
    """Quando waitpid devolve status válido, last_exit_code é populado e
    finished_with_status emite o código mapeado pro POSIX."""
    statuses = []
    session.finished_with_status.connect(lambda c: statuses.append(c))
    session.master_fd = 999
    session.pid = 12345
    # status POSIX: WIFEXITED + WEXITSTATUS=0 → exit code 0.
    with patch("claude_workspaces.pty_session.os.read", return_value=b""), \
         patch("claude_workspaces.pty_session.os.waitpid", return_value=(12345, 0)):
        session._on_readable()
    assert session.last_exit_code == 0
    assert statuses == [0]


def test_finished_with_status_maps_non_zero_exit(session):
    session.master_fd = 999
    session.pid = 12345
    # Status com WEXITSTATUS=42: alto byte do status = 42 << 8.
    status = 42 << 8
    statuses = []
    session.finished_with_status.connect(lambda c: statuses.append(c))
    with patch("claude_workspaces.pty_session.os.read", return_value=b""), \
         patch("claude_workspaces.pty_session.os.waitpid", return_value=(12345, status)):
        session._on_readable()
    assert session.last_exit_code == 42
    assert statuses == [42]


def test_finished_with_status_unknown_when_waitpid_returns_zero(session):
    """waitpid devolvendo (0, 0) significa "não foi possível reapear" —
    last_exit_code vira -1 e o sinal carrega -1."""
    session.master_fd = 999
    session.pid = 12345
    statuses = []
    session.finished_with_status.connect(lambda c: statuses.append(c))
    with patch("claude_workspaces.pty_session.os.read", return_value=b""), \
         patch("claude_workspaces.pty_session.os.waitpid", return_value=(0, 0)), \
         patch("claude_workspaces.pty_session.time.sleep", return_value=None):
        session._on_readable()
    assert session.last_exit_code == -1
    assert statuses == [-1]
