"""Lógica pura de uso/plano — sem dependência de Qt.

Extraída de main_window.py (`_refresh_plan_usage_status` e
`_refresh_plan_usage_updated_label`) para tirar formatação/aritmética de
dentro de um método gigante com chamadas Qt e permitir testes diretos.
Só depende de `datetime` e das constantes de cor de `theme` (módulo puro).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import theme


def color_for_pct(pct: float) -> str:
    """Cor do número conforme a faixa de uso: verde <50, âmbar <80, vermelho ≥80."""
    if pct < 50:
        return theme.SUCCESS
    if pct < 80:
        return theme.WARNING
    return theme.DANGER


def clamp_pct(cost: float, limit: float, ceiling: float = 999.0) -> float:
    """Percentual `cost/limit*100` limitado a `ceiling` (evita exibir 10000%).

    `limit <= 0` retorna 0.0 (sem divisão por zero) — os call sites já passam
    `max(limit, 0.01)`, mas a função é segura por conta própria.
    """
    if limit <= 0:
        return 0.0
    return min(cost / limit * 100.0, ceiling)


def reset_phrase(reset_at: datetime | None, now: datetime) -> str:
    """Tempo até o reset como `Hh MMm` (≥1h, minutos zero-pad) ou `Nm`.

    `reset_at` None → "". Reset no passado → "0m". `now` é injetado para
    testes determinísticos (e deve ter o mesmo tz de `reset_at`).
    """
    if reset_at is None:
        return ""
    delta = reset_at - now
    mins_left = max(int(delta.total_seconds() // 60), 0)
    if mins_left >= 60:
        return f"{mins_left // 60}h{mins_left % 60:02d}m"
    return f"{mins_left}m"


def pct_chip(label_txt: str, pct: float) -> str:
    """Chip HTML `<label> <pct>%` com a cor do número conforme a faixa."""
    return (
        f"<span style='color: {theme.TEXT_FAINT};'>{label_txt} </span>"
        f"<span style='color: {color_for_pct(pct)}; font-weight: 600;'>"
        f"{pct:.0f}%</span>"
    )


def sum_opencode_usage(stats_map) -> tuple[int, float, str]:
    """Agrega stats do OpenCode: soma tokens e custo, acha o modelo com mais
    chamadas. `stats_map` é dict de objetos com `.total_tokens`, `.cost_usd`
    e `.by_model` (dict model→count). Vazio → (0, 0.0, "")."""
    tokens = sum(s.total_tokens for s in stats_map.values())
    cost = sum(s.cost_usd for s in stats_map.values())
    models: dict[str, int] = {}
    for stats in stats_map.values():
        for model, count in stats.by_model.items():
            models[model] = models.get(model, 0) + count
    top_model = max(models.items(), key=lambda kv: kv[1])[0] if models else ""
    return tokens, cost, top_model


def next_weekly_reset(now: datetime) -> datetime:
    """Próxima segunda-feira às 07:00 (mesmo tz de `now`). Se `now` já é
    segunda depois das 07:00, pula para a semana seguinte."""
    days_until_monday = (7 - now.weekday()) % 7
    nxt = (now + timedelta(days=days_until_monday)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )
    if nxt <= now:
        nxt += timedelta(days=7)
    return nxt


def relative_time_phrase(secs: int) -> str:
    """Frase "atualizado há X atrás" a partir de segundos decorridos.
    <60s → "atualizado agora"; depois minutos/horas/dias com singular/plural."""
    secs = max(int(secs), 0)
    if secs < 60:
        return "atualizado agora"
    if secs < 3600:
        mins = secs // 60
        unit = "minuto" if mins == 1 else "minutos"
        return f"atualizado há {mins} {unit} atrás"
    if secs < 86_400:
        hours = secs // 3600
        unit = "hora" if hours == 1 else "horas"
        return f"atualizado há {hours} {unit} atrás"
    days = secs // 86_400
    unit = "dia" if days == 1 else "dias"
    return f"atualizado há {days} {unit} atrás"
