"""Testes de plugins/events.py — EventBus pub/sub + helpers de catálogo."""

import time

import pytest

from claude_workspaces.plugins.events import (
    EVENT_CATALOG,
    HIGH_FREQUENCY_EVENTS,
    SESSION_STATUSES,
    EventBus,
    is_high_frequency,
    is_known_event,
)

# ---------- helpers de catálogo ----------

def test_is_known_event():
    assert is_known_event("session.created") is True
    assert is_known_event("session.inexistente") is False


def test_is_high_frequency():
    assert is_high_frequency("session.message-sent") is True
    assert is_high_frequency("session.created") is False


def test_catalog_and_statuses_shape():
    assert "workspace.opened" in EVENT_CATALOG
    assert "session.message-sent" in HIGH_FREQUENCY_EVENTS
    assert "running" in SESSION_STATUSES and "error" in SESSION_STATUSES


# ---------- subscribe / publish ----------

def test_publish_dispatches_to_subscriber():
    bus = EventBus()
    got = []
    bus.subscribe("p1", "session.created", lambda payload: got.append(payload))
    n = bus.publish("session.created", {"sessionId": "s1"})
    assert n == 1
    assert got == [{"sessionId": "s1"}]


def test_publish_no_subscribers_returns_zero():
    bus = EventBus()
    assert bus.publish("session.created", {}) == 0


def test_publish_multiple_subscribers():
    bus = EventBus()
    calls = []
    bus.subscribe("p1", "workspace.opened", lambda p: calls.append("a"))
    bus.subscribe("p2", "workspace.opened", lambda p: calls.append("b"))
    assert bus.publish("workspace.opened", {"workspaceId": "w"}) == 2
    assert sorted(calls) == ["a", "b"]


def test_publish_unknown_event_still_dispatches():
    # Evento fora do catálogo só loga warning, mas ainda despacha quem escuta.
    bus = EventBus()
    got = []
    bus.subscribe("p1", "custom.event", lambda p: got.append(p))
    assert bus.publish("custom.event", {"x": 1}) == 1
    assert got == [{"x": 1}]


def test_handler_exception_does_not_break_bus():
    bus = EventBus()
    ok = []

    def boom(_p):
        raise RuntimeError("falhou")

    bus.subscribe("bad", "session.created", boom)
    bus.subscribe("good", "session.created", lambda p: ok.append(1))
    # Não deve propagar a exceção; o 2º subscriber ainda roda.
    assert bus.publish("session.created", {}) == 2
    assert ok == [1]


# ---------- unsubscribe ----------

def test_unsubscribe_stops_delivery():
    bus = EventBus()
    got = []
    sub = bus.subscribe("p1", "session.created", lambda p: got.append(p))
    bus.unsubscribe(sub)
    assert bus.publish("session.created", {}) == 0
    assert got == []


def test_unsubscribe_twice_is_safe():
    bus = EventBus()
    sub = bus.subscribe("p1", "session.created", lambda p: None)
    bus.unsubscribe(sub)
    bus.unsubscribe(sub)  # não deve lançar


def test_unsubscribe_plugin_removes_all():
    bus = EventBus()
    bus.subscribe("p1", "session.created", lambda p: None)
    bus.subscribe("p1", "workspace.opened", lambda p: None)
    bus.subscribe("p2", "session.created", lambda p: None)
    removed = bus.unsubscribe_plugin("p1")
    assert removed == 2
    assert bus.subscriber_count() == 1


# ---------- subscriber_count ----------

def test_subscriber_count_total_and_by_event():
    bus = EventBus()
    bus.subscribe("p1", "session.created", lambda p: None)
    bus.subscribe("p2", "session.created", lambda p: None)
    bus.subscribe("p3", "workspace.opened", lambda p: None)
    assert bus.subscriber_count() == 3
    assert bus.subscriber_count("session.created") == 2
    assert bus.subscriber_count("inexistente") == 0


# ---------- throttle / debounce ----------

def test_throttle_drops_rapid_second_call():
    bus = EventBus()
    got = []
    bus.subscribe("p1", "session.message-sent",
                  lambda p: got.append(p), throttle_ms=10_000)
    bus.publish("session.message-sent", {"n": 1})
    bus.publish("session.message-sent", {"n": 2})  # dentro da janela → descartado
    assert got == [{"n": 1}]


def test_throttle_and_debounce_mutually_exclusive():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.subscribe("p1", "session.created", lambda p: None,
                      throttle_ms=100, debounce_ms=100)


def test_debounce_fires_after_delay():
    bus = EventBus()
    got = []
    bus.subscribe("p1", "session.message-sent",
                  lambda p: got.append(p), debounce_ms=20)
    bus.publish("session.message-sent", {"n": 1})
    bus.publish("session.message-sent", {"n": 2})
    # Antes do delay, nada disparou ainda
    assert got == []
    time.sleep(0.1)
    # Só a última chamada dispara (debounce)
    assert got == [{"n": 2}]
