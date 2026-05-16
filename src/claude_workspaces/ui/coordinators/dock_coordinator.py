"""Coordena o RightDock e seus painéis.

Responsabilidades:
- Construir o RightDock com os painéis declarados nas specs
- Propagar set_workspace(ws) pra todos os painéis quando workspace muda
- Persistir estado collapsed dos painéis via Settings
"""

import logging

from PySide6.QtCore import QObject, Signal

from ...models import Workspace
from ...settings import Settings
from ..panels import DockPanel, DockPanelSpec
from ..right_dock import RightDock

log = logging.getLogger(__name__)


class DockCoordinator(QObject):
    """Gerencia o painel direito (Git/Memória/Skills) e a propagação
    de workspace pra eles."""

    panel_toggled = Signal(str, bool)  # re-exposto pra MainWindow logar

    def __init__(
        self,
        settings: Settings,
        specs: list[DockPanelSpec],
        main_window,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.specs = specs
        self._main_window = main_window
        self._panels: list[DockPanel] = []
        self._panels_by_id: dict[str, DockPanel] = {}
        self.widget: RightDock | None = None

    def build(self) -> RightDock:
        """Constrói o RightDock e o devolve pronto pra MainWindow embutir."""
        dock = RightDock()
        dock.setStyleSheet("background: #141414;")
        collapsed = self.settings.right_dock_collapsed or {}

        for spec in self.specs:
            panel = spec.factory(self._main_window)
            dock.add_panel(
                spec.panel_id,
                spec.title,
                panel,
                open_=not collapsed.get(spec.panel_id, not spec.default_open),
            )
            self._panels.append(panel)
            self._panels_by_id[spec.panel_id] = panel

        dock.panel_toggled.connect(self._on_panel_toggled)
        self.widget = dock
        return dock

    def panels(self) -> list[DockPanel]:
        return list(self._panels)

    def panel(self, panel_id: str) -> DockPanel | None:
        return self._panels_by_id.get(panel_id)

    def broadcast_workspace(self, workspace: Workspace | None) -> None:
        """Notifica todos os painéis sobre mudança de workspace. Um
        painel quebrado não derruba os outros (cada chamada é try/except)."""
        for panel in self._panels:
            try:
                panel.set_workspace(workspace)
            except Exception:
                log.exception(
                    "set_workspace falhou em %s", type(panel).__name__
                )

    def _on_panel_toggled(self, panel_id: str, is_open: bool) -> None:
        self.settings.right_dock_collapsed[panel_id] = not is_open
        self.panel_toggled.emit(panel_id, is_open)
