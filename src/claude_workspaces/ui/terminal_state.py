"""Agrupa o estado dos terminais (uma instância por MainWindow).

Antes: 4 dicts soltos em MainWindow (tree_items, activity, inbox,
running_counts) com ciclo de vida disperso. Cada operação manual
arriscava esquecer de limpar um deles → leak.

Agora: TerminalState concentra tudo. `release_tab(tab_id)` é a operação
canônica de cleanup — chame ela e nenhum dict fica órfão.

Sem dependência de Qt — testável sem GUI.
"""

import time
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
    # Tabs aguardando atenção (working → idle transition).
    # Estrutura por entrada:
    #   workspace_id: str
    #   title: str
    #   status: str
    #   added_at: float (time.time())
    #   last_reminded_at: float (0 = ainda nunca lembrou)
    #   snooze_until: float (0 = sem snooze)
    #   dismissed: bool ("já vi, não me avise" — fica na lista, não relembra)
    inbox: dict[int, dict] = field(default_factory=dict)
    # Contagem de tabs rodando por workspace_id
    running_counts: dict[str, int] = field(default_factory=dict)
    # Mapa tab_id → workspace_id pra cleanup em bloco quando um workspace
    # é deletado/fechado. Garantia: se uma tab tem entrada em tree_items
    # ou activity, ela TEM uma entrada aqui.
    tab_workspaces: dict[int, str] = field(default_factory=dict)

    def register_tab(self, tab_id: int, workspace_id: str) -> None:
        """Associa tab_id a workspace_id pra cleanup em bloco."""
        self.tab_workspaces[tab_id] = workspace_id

    def release_tab(self, tab_id: int) -> bool:
        """Remove TUDO relacionado a esse tab_id. Retorna True se o tab
        estava no inbox (caller pode usar pra atualizar o badge)."""
        self.tree_items.pop(tab_id, None)
        self.activity.pop(tab_id, None)
        self.tab_workspaces.pop(tab_id, None)
        return self.inbox.pop(tab_id, None) is not None

    def release_workspace(self, workspace_id: str) -> list[int]:
        """Remove TODOS os tabs registrados pra esse workspace.

        Retorna lista de tab_ids removidos (caller pode emitir tab_removed
        ou recalcular o badge). Idempotente — workspace sem tabs devolve []."""
        to_release = [
            tab_id
            for tab_id, ws_id in self.tab_workspaces.items()
            if ws_id == workspace_id
        ]
        for tab_id in to_release:
            self.release_tab(tab_id)
        self.running_counts.pop(workspace_id, None)
        return to_release

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
        now = time.time()
        # Preserva campos de re-lembrete se a entrada já existia (reentrou
        # do estado working e voltou pra idle de novo — não é entrada nova)
        existing = self.inbox.get(tab_id, {})
        merged = {
            "workspace_id": info.get("workspace_id", existing.get("workspace_id", "")),
            "title": info.get("title", existing.get("title", "")),
            "status": info.get("status", existing.get("status", "")),
            "added_at": existing.get("added_at", now),
            "last_reminded_at": existing.get("last_reminded_at", 0.0),
            "snooze_until": existing.get("snooze_until", 0.0),
            "dismissed": existing.get("dismissed", False),
        }
        self.inbox[tab_id] = merged

    def remove_from_inbox(self, tab_id: int) -> bool:
        return self.inbox.pop(tab_id, None) is not None

    def clear_inbox(self) -> None:
        self.inbox.clear()

    def snooze_inbox(self, tab_id: int, seconds: float) -> bool:
        entry = self.inbox.get(tab_id)
        if entry is None:
            return False
        entry["snooze_until"] = time.time() + seconds
        entry["dismissed"] = False
        return True

    def dismiss_inbox(self, tab_id: int) -> bool:
        """'Já vi' — entrada permanece visível no menu, mas não relembra."""
        entry = self.inbox.get(tab_id)
        if entry is None:
            return False
        entry["dismissed"] = True
        return True
