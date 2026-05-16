"""Agrupa o estado dos terminais (uma instância por MainWindow).

Antes: 4 dicts soltos em MainWindow (tree_items, activity, inbox,
running_counts) com ciclo de vida disperso. Cada operação manual
arriscava esquecer de limpar um deles → leak.

Agora: TerminalState concentra tudo. `release_tab(tab_id)` é a operação
canônica de cleanup — chame ela e nenhum dict fica órfão.

Sem dependência de Qt — testável sem GUI.
"""

from dataclasses import dataclass, field
from typing import Any

# Tipo do valor de activity[tab_id] = (status, is_working, title)
ActivityTuple = tuple[str, bool, str]


@dataclass
class TerminalState:
    """Estado per-tab keyed por tab_id (id() do TerminalWidget)."""

    # Tree item correspondente a cada tab (QTreeWidgetItem; Any pra
    # não depender de Qt aqui)
    tree_items: dict[int, Any] = field(default_factory=dict)
    # (status, is_working, title) — mantido como tupla por compat
    activity: dict[int, ActivityTuple] = field(default_factory=dict)
    # Tabs aguardando atenção (working → idle transition)
    inbox: dict[int, dict] = field(default_factory=dict)
    # Contagem de tabs rodando por workspace_id
    running_counts: dict[str, int] = field(default_factory=dict)

    def release_tab(self, tab_id: int) -> bool:
        """Remove TUDO relacionado a esse tab_id. Retorna True se o tab
        estava no inbox (caller pode usar pra atualizar o badge)."""
        self.tree_items.pop(tab_id, None)
        self.activity.pop(tab_id, None)
        return self.inbox.pop(tab_id, None) is not None

    def any_working(self) -> bool:
        return any(working for _status, working, _title in self.activity.values())

    def set_running_count(self, workspace_id: str, count: int) -> None:
        if count <= 0:
            self.running_counts.pop(workspace_id, None)
        else:
            self.running_counts[workspace_id] = count

    def running_count_of(self, workspace_id: str) -> int:
        return self.running_counts.get(workspace_id, 0)

    def add_to_inbox(self, tab_id: int, info: dict) -> None:
        self.inbox[tab_id] = info

    def remove_from_inbox(self, tab_id: int) -> bool:
        return self.inbox.pop(tab_id, None) is not None

    def clear_inbox(self) -> None:
        self.inbox.clear()
