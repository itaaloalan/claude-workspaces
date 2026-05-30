"""Lógica pura da sidebar — sem dependência de Qt.

Extraída de main_window.py (`_rebuild_list`, `_refresh_activity_badges`) para
permitir testes unitários diretos e manter o widget focado em renderização.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Workspace


def partition_workspaces(
    workspaces: list[Workspace],
) -> tuple[list[Workspace], list[Workspace]]:
    """Separa os workspaces visíveis em (fixados, regulares).

    Minimizados saem de ambas as listas (viram chips na faixa). A ordem
    relativa de cada grupo é preservada.
    """
    visible = [ws for ws in workspaces if not ws.minimized]
    pinned = [ws for ws in visible if ws.pinned]
    regular = [ws for ws in visible if not ws.pinned]
    return pinned, regular


def disambiguated_title(
    base_title: str, tab_id: int, sibling_ids: list[int]
) -> str:
    """Prepende `#N ` ao título do console, onde N é a posição entre os
    irmãos do mesmo workspace ordenados por tab_id crescente (mais antigo
    = #1). `tab_id` é incluído mesmo que ainda não esteja em sibling_ids.

    Título vazio passa direto (nada a numerar).
    """
    if not base_title:
        return base_title
    ids = sorted(set(int(s) for s in sibling_ids) | {int(tab_id)})
    position = ids.index(int(tab_id)) + 1
    return f"#{position} {base_title}"


def format_activity_badge(working: int, total: int) -> tuple[str, str]:
    """Texto do badge de atividade dos workspaces no ActivityBar.

    Retorna (badge, tooltip). Sem workspaces → ("", ""). Sem nenhum
    trabalhando → só o total; caso contrário "trabalhando/total".
    """
    if total <= 0:
        return "", ""
    badge = f"{working}/{total}" if working > 0 else str(total)
    tip = (
        f"{working} trabalhando · {total - working} ocioso(s) · "
        f"{total} no total"
    )
    return badge, tip
