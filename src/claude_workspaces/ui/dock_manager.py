"""Wrapper sobre PySide6QtAds.CDockManager.

Expõe uma API estreita pros 3 slots do shell de workspaces (sidebar à
esquerda, conteúdo+terminal no centro, painel direito) e abstrai
persistência de layout via QByteArray serializado em base64.

Fase 1 da migração IDE-like: substitui só o body_splitter externo; o
right_splitter vertical (conteúdo/terminal) continua sendo um QSplitter
dentro do dock central.
"""

from __future__ import annotations

import base64

import PySide6QtAds as ads
from PySide6.QtCore import QByteArray, QObject
from PySide6.QtWidgets import QMainWindow, QWidget


class WorkspaceDockManager(QObject):
    """Donos dos 3 docks do shell de workspaces."""

    def __init__(self, host: QMainWindow) -> None:
        super().__init__(host)
        # Auto-hide / float / pin habilitados; sem botão de fechar nos
        # docks principais (sidebar/right) — só toggle de visibilidade.
        ads.CDockManager.setConfigFlag(ads.CDockManager.OpaqueSplitterResize, True)
        ads.CDockManager.setConfigFlag(ads.CDockManager.XmlAutoFormattingEnabled, True)
        ads.CDockManager.setConfigFlag(ads.CDockManager.FocusHighlighting, False)
        ads.CDockManager.setAutoHideConfigFlags(ads.CDockManager.DefaultAutoHideConfig)

        self._manager = ads.CDockManager(host)
        self._docks: dict[str, ads.CDockWidget] = {}

    # ---------- API pública ----------

    @property
    def widget(self) -> ads.CDockManager:
        return self._manager

    def add_center(self, widget: QWidget, title: str = "Workspace") -> ads.CDockWidget:
        dock = self._make_dock(title, widget, closable=False, movable=False, floatable=False)
        self._manager.addDockWidget(ads.CenterDockWidgetArea, dock)
        return dock

    def add_left(self, widget: QWidget, title: str = "Workspaces") -> ads.CDockWidget:
        dock = self._make_dock(title, widget, closable=False)
        self._manager.addDockWidget(ads.LeftDockWidgetArea, dock)
        return dock

    def add_right(self, widget: QWidget, title: str = "Ferramentas") -> ads.CDockWidget:
        dock = self._make_dock(title, widget, closable=False)
        self._manager.addDockWidget(ads.RightDockWidgetArea, dock)
        return dock

    def dock(self, key: str) -> ads.CDockWidget | None:
        return self._docks.get(key)

    def toggle(self, key: str) -> None:
        d = self._docks.get(key)
        if d is None:
            return
        d.toggleView(d.isClosed())

    def is_visible(self, key: str) -> bool:
        d = self._docks.get(key)
        return bool(d and not d.isClosed())

    # ---------- persistência ----------

    def save_state_b64(self) -> str:
        """Serializa layout como base64 string (cabe em settings.json)."""
        ba: QByteArray = self._manager.saveState()
        return bytes(ba.toBase64()).decode("ascii")

    def restore_state_b64(self, payload: str | None) -> bool:
        if not payload:
            return False
        try:
            ba = QByteArray.fromBase64(payload.encode("ascii"))
        except Exception:
            return False
        return bool(self._manager.restoreState(ba))

    # ---------- internos ----------

    def _make_dock(
        self,
        title: str,
        widget: QWidget,
        *,
        closable: bool = True,
        movable: bool = True,
        floatable: bool = True,
    ) -> ads.CDockWidget:
        dock = ads.CDockWidget(title)
        dock.setWidget(widget)
        feats = ads.CDockWidget.NoDockWidgetFeatures
        if closable:
            feats |= ads.CDockWidget.DockWidgetClosable
        if movable:
            feats |= ads.CDockWidget.DockWidgetMovable
        if floatable:
            feats |= ads.CDockWidget.DockWidgetFloatable
        dock.setFeatures(feats)
        # Chave estável = título lowercased; usado pra toggle()
        self._docks[title.lower()] = dock
        return dock
