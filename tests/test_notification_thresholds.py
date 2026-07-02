"""Testes da lógica pura de thresholds de notificação (TDD).

Escritos antes de notifications/thresholds.py existir. Travam a decisão de
nível de aviso de custo (extraída de _maybe_emit_cost_warning) e o cálculo de
execução longa (extraído de _scan_long_running) do main_window.py.
"""

from claude_workspaces.notifications.thresholds import (
    cost_warning_levels,
    cost_warning_transitions,
    long_running_minutes,
)

# ---------- cost_warning_levels ----------

def test_cost_warning_empty():
    assert cost_warning_levels([]) == []


def test_cost_warning_below_threshold_excluded():
    assert cost_warning_levels([("5h", 79.9)]) == []


def test_cost_warning_at_80_is_alto():
    assert cost_warning_levels([("5h", 80.0)]) == [("5h", 80.0, "alto")]


def test_cost_warning_below_95_is_alto():
    assert cost_warning_levels([("7d", 94.9)]) == [("7d", 94.9, "alto")]


def test_cost_warning_at_95_is_critico():
    assert cost_warning_levels([("7d", 95.0)]) == [("7d", 95.0, "crítico")]


def test_cost_warning_above_95_is_critico():
    assert cost_warning_levels([("5h", 120.0)]) == [("5h", 120.0, "crítico")]


def test_cost_warning_mixed_filters_and_labels():
    pairs = [("5h", 50.0), ("7d", 85.0), ("7d-sonnet", 99.0)]
    assert cost_warning_levels(pairs) == [
        ("7d", 85.0, "alto"),
        ("7d-sonnet", 99.0, "crítico"),
    ]


def test_cost_warning_custom_thresholds():
    out = cost_warning_levels([("x", 60.0)], warn=50.0, crit=70.0)
    assert out == [("x", 60.0, "alto")]


# ---------- cost_warning_transitions ----------

def test_transitions_first_crossing_notifies():
    out, state = cost_warning_transitions([("5h", 85.0)], {})
    assert out == [("5h", 85.0, "alto")]
    assert state == {"5h": "alto"}


def test_transitions_same_level_stays_silent():
    # Poll seguinte com a janela ainda em "alto" — nada de re-notificar,
    # mesmo com o pct variando (era a fonte do popup-por-minuto).
    out, state = cost_warning_transitions([("5h", 87.0)], {"5h": "alto"})
    assert out == []
    assert state == {"5h": "alto"}


def test_transitions_escalation_alto_para_critico_notifies():
    out, state = cost_warning_transitions([("5h", 96.0)], {"5h": "alto"})
    assert out == [("5h", 96.0, "crítico")]
    assert state == {"5h": "crítico"}


def test_transitions_downgrade_critico_para_alto_stays_silent():
    out, state = cost_warning_transitions([("5h", 90.0)], {"5h": "crítico"})
    assert out == []
    # estado acompanha o nível atual — se subir de novo pra crítico, notifica.
    assert state == {"5h": "alto"}


def test_transitions_drop_below_warn_rearms():
    out, state = cost_warning_transitions([("5h", 40.0)], {"5h": "alto"})
    assert out == []
    assert state == {}
    # cruzou de novo depois de rearmado → notifica de novo
    out2, state2 = cost_warning_transitions([("5h", 82.0)], state)
    assert out2 == [("5h", 82.0, "alto")]
    assert state2 == {"5h": "alto"}


def test_transitions_multiple_windows_independent():
    prev = {"7d": "alto"}
    out, state = cost_warning_transitions(
        [("5h", 85.0), ("7d", 86.0), ("7d-sonnet", 10.0)], prev
    )
    assert out == [("5h", 85.0, "alto")]
    assert state == {"5h": "alto", "7d": "alto"}


# ---------- long_running_minutes ----------

def test_long_running_below_threshold_is_none():
    assert long_running_minutes(started=1000.0, now=1000.0 + 299) is None


def test_long_running_at_threshold_returns_minutes():
    # 300s = 5min exatos
    assert long_running_minutes(started=0.0, now=300.0) == 5


def test_long_running_above_threshold_rounds_down():
    # 6min30s → 6
    assert long_running_minutes(started=0.0, now=390.0) == 6


def test_long_running_custom_threshold():
    assert long_running_minutes(started=0.0, now=120.0, threshold_seconds=60) == 2


def test_long_running_just_below_custom_threshold():
    assert long_running_minutes(started=0.0, now=59.0, threshold_seconds=60) is None
