"""Wrapper sobre PySide6QtAds.CDockManager.

Expõe uma API estreita pros 3 slots do shell de workspaces (sidebar à
esquerda, conteúdo+terminal no centro, painel direito) e abstrai
persistência de layout via QByteArray serializado em base64.

Fase 1 da migração IDE-like: substitui só o body_splitter externo; o
right_splitter vertical (conteúdo/terminal) continua sendo um QSplitter
dentro do dock central.
"""

from __future__ import annotations

import PySide6QtAds as ads
from PySide6.QtCore import QByteArray, QObject, QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMainWindow, QWidget


def _glyph_icon(glyph: str, size: int = 14, color: str = "#c8c8c8") -> QIcon:
    """Renderiza um glyph unicode numa QPixmap transparente. Usado pros
    botões de title bar do QtAds — os ícones default são pretos e somem
    no tema dark."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(QPen(QColor(color)))
    font = QFont()
    font.setPixelSize(size - 2)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def _install_dark_icons() -> None:
    """Substitui os ícones default do QtAds por glyphs unicode claros.
    Chamado uma vez quando o primeiro CDockManager é criado."""
    ip = ads.CDockManager.iconProvider()
    ip.registerCustomIcon(ads.TabCloseIcon, _glyph_icon("✕"))
    ip.registerCustomIcon(ads.DockAreaCloseIcon, _glyph_icon("✕"))
    ip.registerCustomIcon(ads.DockAreaMenuIcon, _glyph_icon("⋮"))
    ip.registerCustomIcon(ads.DockAreaUndockIcon, _glyph_icon("⧉"))
    ip.registerCustomIcon(ads.DockAreaMinimizeIcon, _glyph_icon("—"))
    ip.registerCustomIcon(ads.AutoHideIcon, _glyph_icon("📌"))


# QSS dark pro QtAds — o default tem gradiente light nas title bars que
# destoa do tema escuro. Cobre tab bar, area title bar, splitter handle
# e dock widget. Cores alinhadas com ui/theme.py.
_ADS_DARK_QSS = """
ads--CDockContainerWidget,
ads--CDockAreaWidget,
ads--CDockWidget {
    background: #181818;
    color: #e6e6e6;
}
ads--CDockAreaTitleBar {
    background: #181818;
    border-bottom: 1px solid #2a2a2a;
    padding: 0;
}
ads--CDockWidgetTab {
    background: #1f1f1f;
    border: 0;
    border-right: 1px solid #2a2a2a;
    padding: 4px 12px;
    min-height: 22px;
}
ads--CDockWidgetTab QLabel,
ads--CDockWidgetTab ads--CElidingLabel {
    color: #9aa0a6;
    background: transparent;
}
ads--CDockWidgetTab[activeTab="true"] {
    background: #181818;
    border-bottom: 2px solid #3d6ea8;
}
ads--CDockWidgetTab[activeTab="true"] QLabel,
ads--CDockWidgetTab[activeTab="true"] ads--CElidingLabel {
    color: #f2f2f2;
}
ads--CTitleBarButton {
    background: transparent;
    border: 0;
    padding: 3px;
    min-width: 18px;
    min-height: 18px;
}
ads--CTitleBarButton:hover {
    background: #2a2a2a;
    border-radius: 3px;
}
ads--CDockSplitter::handle {
    background: #2a2a2a;
}
ads--CDockSplitter::handle:hover {
    background: #3d6ea8;
}
ads--CFloatingDockContainer {
    background: #181818;
    border: 1px solid #2a2a2a;
}
"""


class WorkspaceDockManager(QObject):
    """Donos dos 3 docks do shell de workspaces."""

    def __init__(self, host: QMainWindow) -> None:
        super().__init__(host)
        # Auto-hide / float / pin habilitados; sem botão de fechar nos
        # docks principais (sidebar/right) — só toggle de visibilidade.
        ads.CDockManager.setConfigFlag(ads.CDockManager.OpaqueSplitterResize, True)
        ads.CDockManager.setConfigFlag(ads.CDockManager.XmlAutoFormattingEnabled, True)
        ads.CDockManager.setConfigFlag(ads.CDockManager.FocusHighlighting, False)
        # Desliga botão de fechar no dock area (independe das features do
        # CDockWidget — o area sempre desenha close se isso for True).
        ads.CDockManager.setConfigFlag(ads.CDockManager.DockAreaHasCloseButton, False)
        # Remove os botões inúteis da title bar do dock central: ⋮ (tabs menu)
        # e undock — não temos múltiplas abas pra menu nem suporte a flutuar,
        # então só poluíam o canto superior direito.
        ads.CDockManager.setConfigFlag(ads.CDockManager.DockAreaHasTabsMenuButton, False)
        ads.CDockManager.setConfigFlag(ads.CDockManager.DockAreaHasUndockButton, False)
        # Duplo-clique no título NÃO destaca o dock pra janela flutuante —
        # complementa movable/floatable=False dos docks pra impedir detach.
        ads.CDockManager.setConfigFlag(ads.CDockManager.DoubleClickUndocksWidget, False)
        ads.CDockManager.setAutoHideConfigFlags(ads.CDockManager.DefaultAutoHideConfig)
        # Remove o pin de auto-hide da title bar — auto-hide é controlado por
        # toggle externo, o botão na aba não servia.
        ads.CDockManager.setAutoHideConfigFlag(
            ads.CDockManager.DockAreaHasAutoHideButton, False
        )

        self._manager = ads.CDockManager(host)
        _install_dark_icons()
        self._manager.setStyleSheet(_ADS_DARK_QSS)
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
        # movable/floatable=False: a sidebar não pode ser arrastada pra fora
        # nem flutuar — fica sempre ancorada (evita o dock "soltar" da janela).
        dock = self._make_dock(title, widget, closable=False, movable=False, floatable=False)
        self._manager.addDockWidget(ads.LeftDockWidgetArea, dock)
        return dock

    def add_right(self, widget: QWidget, title: str = "Ferramentas") -> ads.CDockWidget:
        # Idem sidebar: dock direito não destaca nem flutua.
        dock = self._make_dock(title, widget, closable=False, movable=False, floatable=False)
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

    def redock_right(self, key: str) -> None:
        """Re-ancora um dock que se soltou pra um container flutuante de
        volta à direita da janela principal. Estados salvos antigos às vezes
        gravavam o dock como floating+closed — aí ele 'aparecia fora do app'
        numa janela flutuante separada, em vez de ancorado na coluna."""
        d = self._docks.get(key)
        if d is None:
            return
        if d.isFloating() or d.dockContainer() is not self._manager:
            self._manager.removeDockWidget(d)
            self._manager.addDockWidget(ads.RightDockWidgetArea, d)
        d.toggleView(True)

    def redock_left(self, key: str) -> None:
        """Re-ancora um dock que se soltou pra um container flutuante de
        volta à esquerda da janela principal. Mesma lógica do redock_right
        mas usa LeftDockWidgetArea — necessário pro sidebar que deve ficar
        fixo na coluna esquerda."""
        d = self._docks.get(key)
        if d is None:
            return
        if d.isFloating() or d.dockContainer() is not self._manager:
            self._manager.removeDockWidget(d)
            self._manager.addDockWidget(ads.LeftDockWidgetArea, d)
        d.toggleView(True)

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
