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


# Ordem de severidade dos níveis de cost_warning — usada pra só notificar
# quando o nível SOBE (nada → alto → crítico). Queda de nível não notifica.
_LEVEL_RANK = {"alto": 1, "crítico": 2}


def cost_warning_transitions(
    pairs: list[tuple[str, float]],
    previous: dict[str, str],
    *,
    warn: float = 80.0,
    crit: float = 95.0,
) -> tuple[list[tuple[str, float, str]], dict[str, str]]:
    """Filtra `cost_warning_levels` pra só devolver TRANSIÇÕES de nível.

    `previous` mapeia `window_label -> nível` já notificado. Devolve
    `(a_notificar, novo_previous)`:

    - janela cruzou 80% (ou subiu de "alto" pra "crítico") → entra na lista;
    - janela segue no mesmo nível → silêncio (era isso que gerava um popup
      por poll: o snapshot chega a cada minuto e o mesmo "alto" re-notificava
      a cada cooldown);
    - janela caiu abaixo de 80% → sai do `novo_previous`, rearmando o aviso
      pra próxima vez que cruzar.
    """
    levels = cost_warning_levels(pairs, warn=warn, crit=crit)
    current = {label: level for label, _pct, level in levels}
    to_notify = [
        (label, pct, level)
        for label, pct, level in levels
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(previous.get(label, ""), 0)
    ]
    return to_notify, current


def long_running_minutes(
    started: float, now: float, threshold_seconds: float = 300.0
) -> int | None:
    """Minutos decorridos desde `started` se passou de `threshold_seconds`,
    senão `None`. `started`/`now` em segundos (ex.: `time.monotonic()`)."""
    elapsed = now - started
    if elapsed < threshold_seconds:
        return None
    return int(elapsed // 60)
