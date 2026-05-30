"""Lógica pura de thresholds de notificação — sem dependência de Qt.

Extraída de main_window.py (`_maybe_emit_cost_warning`, `_scan_long_running`)
para isolar a decisão (aritmética + faixas) do disparo (NotificationService),
permitindo testar os limites sem construir a MainWindow.
"""

from __future__ import annotations


def cost_warning_levels(
    pairs: list[tuple[str, float]],
    *,
    warn: float = 80.0,
    crit: float = 95.0,
) -> list[tuple[str, float, str]]:
    """Decide quais janelas de uso merecem aviso de custo.

    Recebe `(window_label, pct)` já extraídos. Devolve, em ordem, só as
    janelas com `pct >= warn`, cada uma com o nível: `"crítico"` (≥ crit)
    ou `"alto"`.
    """
    out: list[tuple[str, float, str]] = []
    for label, pct in pairs:
        if pct < warn:
            continue
        level = "crítico" if pct >= crit else "alto"
        out.append((label, pct, level))
    return out


def long_running_minutes(
    started: float, now: float, threshold_seconds: float = 300.0
) -> int | None:
    """Minutos decorridos desde `started` se passou de `threshold_seconds`,
    senão `None`. `started`/`now` em segundos (ex.: `time.monotonic()`)."""
    elapsed = now - started
    if elapsed < threshold_seconds:
        return None
    return int(elapsed // 60)
