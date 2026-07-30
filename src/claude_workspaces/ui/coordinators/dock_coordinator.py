"""Coordena o RightDock e seus painéis.

Responsabilidades:
- Construir o RightDock com os painéis declarados nas specs
- Propagar set_workspace(ws) SÓ pro painel ativo (dirty-refresh: os
  ocultos ficam marcados e recebem o workspace quando forem ativados —
  painel escondido não paga refresh na troca de workspace)
- Persistir o painel ativo via Settings (right_dock_active_panel)
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
        # Dirty-refresh: workspace pendente + ids que ainda não o receberam.
        self._pending_ws: Workspace | None = None
        self._dirty: set[str] = set()

    def build(self) -> RightDock:
        """Constrói o RightDock e o devolve pronto pra MainWindow embutir."""
        dock = RightDock()
        active = self.settings.right_dock_active_panel or ""
        if active not in {s.panel_id for s in self.specs}:
            active = next(
                (s.panel_id for s in self.specs if s.default_open),
                self.specs[0].panel_id if self.specs else "",
            )

        for spec in self.specs:
            panel = spec.factory(self._main_window)
            dock.add_panel(
                spec.panel_id,
                spec.title,
                panel,
                open_=spec.panel_id == active,
                icon=spec.icon,
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
        """Aplica o workspace no painel ATIVO e marca os demais como
        dirty — eles recebem o set_workspace quando forem ativados.
        Cada aplicação é cronometrada ([SWITCH-PERF])."""
        self._pending_ws = workspace
        self._dirty = set(self._panels_by_id.keys())
        active = self.widget.active_panel() if self.widget else None
        if active is not None:
            self._apply_workspace(active)

    def _apply_workspace(self, panel_id: str) -> None:
        """set_workspace(pendente) num painel específico. Um painel
        quebrado não derruba os outros."""
        import time
        panel = self._panels_by_id.get(panel_id)
        if panel is None:
            return
        self._dirty.discard(panel_id)
        t0 = time.perf_counter()
        try:
            panel.set_workspace(self._pending_ws)
        except Exception:
            log.exception(
                "set_workspace falhou em %s", type(panel).__name__
            )
        log.info(
            "[SWITCH-PERF] panel=%s dt=%.1fms",
            type(panel).__name__, (time.perf_counter() - t0) * 1000,
        )

    def _on_panel_toggled(self, panel_id: str, is_open: bool) -> None:
        if is_open:
            self.settings.right_dock_active_panel = panel_id
            # Painel acabou de ficar visível com workspace defasado —
            # aplica agora (dirty-refresh).
            if panel_id in self._dirty:
                self._apply_workspace(panel_id)
        self.panel_toggled.emit(panel_id, is_open)
