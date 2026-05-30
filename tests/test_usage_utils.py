"""Testes da lógica pura de uso/plano — extraída de main_window.py (TDD).

Escritos ANTES de ui/usage_utils.py existir, travando o comportamento que
estava preso dentro de _refresh_plan_usage_status (closures _color, _chip,
_reset_phrase, _sum) e dos cálculos duplicados de % e reset semanal.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from claude_workspaces.ui import theme
from claude_workspaces.ui.usage_utils import (
    clamp_pct,
    color_for_pct,
    next_weekly_reset,
    pct_chip,
    relative_time_phrase,
    reset_phrase,
    sum_opencode_usage,
)

# ---------- color_for_pct ----------

def test_color_low_is_success():
    assert color_for_pct(0) == theme.SUCCESS
    assert color_for_pct(49.9) == theme.SUCCESS


def test_color_mid_is_warning():
    assert color_for_pct(50) == theme.WARNING
    assert color_for_pct(79.9) == theme.WARNING


def test_color_high_is_danger():
    assert color_for_pct(80) == theme.DANGER
    assert color_for_pct(100) == theme.DANGER
    assert color_for_pct(999) == theme.DANGER


# ---------- clamp_pct ----------

def test_clamp_pct_normal():
    assert clamp_pct(50, 100) == 50.0


def test_clamp_pct_ceiling():
    # 5000/100*100 = 5000% → teto 999
    assert clamp_pct(5000, 100) == 999.0


def test_clamp_pct_custom_ceiling():
    assert clamp_pct(5000, 100, ceiling=500.0) == 500.0


def test_clamp_pct_zero_limit_safe():
    # Não deve dividir por zero
    assert clamp_pct(10, 0) == 0.0


def test_clamp_pct_zero_cost():
    assert clamp_pct(0, 100) == 0.0


# ---------- reset_phrase ----------

def test_reset_phrase_none():
    assert reset_phrase(None, datetime.now(UTC)) == ""


def test_reset_phrase_minutes_only():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert reset_phrase(now + timedelta(minutes=44), now) == "44m"


def test_reset_phrase_hours_and_minutes_zero_padded():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert reset_phrase(now + timedelta(hours=5, minutes=3), now) == "5h03m"


def test_reset_phrase_exactly_one_hour():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert reset_phrase(now + timedelta(hours=1), now) == "1h00m"


def test_reset_phrase_past_is_zero():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert reset_phrase(now - timedelta(minutes=30), now) == "0m"


# ---------- pct_chip ----------

def test_pct_chip_contains_label_and_percent():
    chip = pct_chip("5h", 34.0)
    assert "5h" in chip
    assert "34%" in chip


def test_pct_chip_rounds_to_integer():
    assert "35%" in pct_chip("x", 34.6)


def test_pct_chip_uses_color_for_pct():
    assert theme.SUCCESS in pct_chip("x", 10)
    assert theme.DANGER in pct_chip("x", 95)


# ---------- sum_opencode_usage ----------

def _stats(total, cost, by_model):
    return SimpleNamespace(total_tokens=total, cost_usd=cost, by_model=by_model)


def test_sum_empty():
    assert sum_opencode_usage({}) == (0, 0.0, "")


def test_sum_aggregates_tokens_and_cost():
    m = {
        "a": _stats(100, 1.5, {"gpt-4": 80, "gpt-3": 20}),
        "b": _stats(50, 0.5, {"gpt-4": 50}),
    }
    tokens, cost, top = sum_opencode_usage(m)
    assert tokens == 150
    assert cost == 2.0
    # gpt-4: 80+50=130 > gpt-3: 20
    assert top == "gpt-4"


def test_sum_top_model_single():
    m = {"a": _stats(10, 0.1, {"sonnet": 10})}
    assert sum_opencode_usage(m)[2] == "sonnet"


# ---------- next_weekly_reset ----------

def test_next_weekly_reset_from_wednesday():
    # Quarta 30/05/2026? 2026-05-30 é sábado. Use uma quarta real:
    wed = datetime(2026, 5, 27, 15, 0)  # 2026-05-27 = quarta
    assert wed.weekday() == 2
    nxt = next_weekly_reset(wed)
    assert nxt.weekday() == 0  # segunda
    assert (nxt.hour, nxt.minute) == (7, 0)
    assert nxt > wed


def test_next_weekly_reset_monday_before_7am():
    mon = datetime(2026, 6, 1, 6, 0)  # 2026-06-01 = segunda, antes das 7h
    assert mon.weekday() == 0
    nxt = next_weekly_reset(mon)
    # Mesma segunda às 7h (ainda no futuro)
    assert nxt.weekday() == 0
    assert nxt.day == 1
    assert nxt.hour == 7


def test_next_weekly_reset_monday_after_7am_skips_week():
    mon = datetime(2026, 6, 1, 9, 0)  # segunda, depois das 7h
    nxt = next_weekly_reset(mon)
    assert nxt.weekday() == 0
    assert nxt.day == 8  # próxima segunda
    assert nxt.hour == 7


# ---------- relative_time_phrase ----------

def test_relative_now():
    assert relative_time_phrase(0) == "atualizado agora"
    assert relative_time_phrase(59) == "atualizado agora"


def test_relative_minutes_singular_plural():
    assert relative_time_phrase(60) == "atualizado há 1 minuto atrás"
    assert relative_time_phrase(120) == "atualizado há 2 minutos atrás"


def test_relative_hours_singular_plural():
    assert relative_time_phrase(3600) == "atualizado há 1 hora atrás"
    assert relative_time_phrase(7200) == "atualizado há 2 horas atrás"


def test_relative_days_singular_plural():
    assert relative_time_phrase(86_400) == "atualizado há 1 dia atrás"
    assert relative_time_phrase(172_800) == "atualizado há 2 dias atrás"
