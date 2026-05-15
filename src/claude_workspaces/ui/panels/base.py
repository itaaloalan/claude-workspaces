"""Contrato dos panels que podem ser embarcados no RightDock.

Usa typing.Protocol — não força herança. Os panels existentes
(GitPanel, SkillsPanel, MemoryPanel, etc.) já satisfazem
estruturalmente; o tipo serve só pra MainWindow saber o que esperar
quando itera sobre a lista de painéis.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ...models import Workspace


@runtime_checkable
class DockPanel(Protocol):
    """Mínimo que um painel do dock precisa implementar.

    A regra é simples: a MainWindow chama `set_workspace(ws)` toda vez
    que o usuário troca de workspace na sidebar (ou seleciona um filho
    do tree). O painel decide o que mostrar baseado em ws.

    set_workspace(None) significa que nenhum workspace está selecionado
    — o painel deve esvaziar/desabilitar seu estado.
    """

    def set_workspace(self, workspace: Workspace | None) -> None: ...


@dataclass(frozen=True)
class DockPanelSpec:
    """Spec de um painel pro RightDock — desacopla MainWindow da
    instanciação dos panels. A factory recebe a MainWindow (pra
    poder pegar dependências como `details`, `settings`) e devolve
    o panel pronto."""

    panel_id: str
    title: str
    factory: Callable[[object], DockPanel]
    default_open: bool = False
