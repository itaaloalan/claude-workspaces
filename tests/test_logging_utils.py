"""Testes do decorator @log_exceptions."""

import logging

from claude_workspaces.logging_utils import log_exceptions


def test_logs_and_returns_default(caplog):
    @log_exceptions(message="boom", default=42)
    def fn():
        raise RuntimeError("xx")

    with caplog.at_level(logging.ERROR):
        out = fn()
    assert out == 42
    assert "boom" in caplog.text
    assert "RuntimeError" in caplog.text


def test_no_exception_passthrough():
    @log_exceptions()
    def fn(x: int) -> int:
        return x + 1

    assert fn(5) == 6


def test_reraise(caplog):
    @log_exceptions(reraise=True)
    def fn():
        raise ValueError("nope")

    raised = False
    with caplog.at_level(logging.ERROR):
        try:
            fn()
        except ValueError:
            raised = True
    assert raised
    assert "Exceção em" in caplog.text


def test_default_message_uses_qualname(caplog):
    @log_exceptions()
    def my_func():
        raise Exception("ka")

    with caplog.at_level(logging.ERROR):
        my_func()
    assert "my_func" in caplog.text
