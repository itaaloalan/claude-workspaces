"""QSS global consolidado, gerado a partir dos tokens de ui/theme.py.

Único ponto de estilo app-wide: `build_app_qss()` vai no
`QApplication.setStyleSheet` (menus, tooltips, dialogs, scrollbars) e
`ads_qss()` no `CDockManager.setStyleSheet` — o QtAds instala um
stylesheet default próprio no widget (que venceria o QSS de aplicação),
então precisa ser sobrescrito no nível do manager.
"""

from . import theme


def build_app_qss() -> str:
    return f"""
QMenu {{
    background: {theme.BG_ELEVATED};
    color: {theme.TEXT_PRIMARY};
    border: 1px solid {theme.BORDER_INPUT};
    border-radius: {theme.RADIUS_MD}px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 22px 6px 18px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {theme.PRIMARY_SELECTION_BG};
    color: {theme.TEXT_BRIGHT};
}}
QMenu::item:disabled {{
    color: {theme.TEXT_FAINT};
}}
QMenu::separator {{
    height: 1px;
    background: {theme.BORDER_INPUT};
    margin: 4px 8px;
}}
QToolTip {{
    background: {theme.BG_ELEVATED};
    color: {theme.TEXT_PRIMARY};
    border: 1px solid {theme.BORDER_INPUT};
    padding: 4px 6px;
}}
QMessageBox, QInputDialog, QFileDialog {{
    background: {theme.BG_DARK};
    color: {theme.TEXT_PRIMARY};
}}
QMessageBox QLabel, QInputDialog QLabel {{
    color: {theme.TEXT_PRIMARY};
    background: transparent;
}}
/* Scrollbar global — espelha o visual minimalista do viewport do
 * console (terminal.html): 8px, sem track, thumb sutil.
 * Pega QListWidget/QTreeWidget/QScrollArea/QPlainTextEdit/QTextBrowser
 * etc. de uma vez. */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 70);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    background: transparent;
    border: 0;
    height: 0;
    width: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {{
    background: transparent;
    border: 0;
    width: 0;
    height: 0;
}}
QScrollBar::corner {{
    background: transparent;
}}
"""


def ads_qss() -> str:
    """Dark pro QtAds — o default tem gradiente light nas title bars.
    Cobre tab bar, area title bar, splitter handle e dock widget."""
    return f"""
ads--CDockContainerWidget,
ads--CDockAreaWidget,
ads--CDockWidget {{
    background: {theme.BG_DARK};
    color: {theme.TEXT_PRIMARY};
}}
ads--CDockAreaTitleBar {{
    background: {theme.BG_DARK};
    border-bottom: 1px solid {theme.BORDER};
    padding: 0;
}}
ads--CDockWidgetTab {{
    background: {theme.BG_SURFACE};
    border: 0;
    border-right: 1px solid {theme.BORDER};
    padding: 4px 12px;
    min-height: 26px;
}}
ads--CDockWidgetTab QLabel,
ads--CDockWidgetTab ads--CElidingLabel {{
    color: {theme.PR_DRAFT};
    background: transparent;
}}
ads--CDockWidgetTab[activeTab="true"] {{
    background: {theme.BG_DARK};
    border-bottom: 2px solid {theme.PRIMARY};
}}
ads--CDockWidgetTab[activeTab="true"] QLabel,
ads--CDockWidgetTab[activeTab="true"] ads--CElidingLabel {{
    color: {theme.TEXT_PRIMARY};
}}
ads--CTitleBarButton {{
    background: transparent;
    border: 0;
    padding: 3px;
    min-width: 18px;
    min-height: 18px;
}}
ads--CTitleBarButton:hover {{
    background: {theme.BORDER};
    border-radius: 3px;
}}
ads--CDockSplitter::handle {{
    background: {theme.BORDER};
}}
ads--CDockSplitter::handle:hover {{
    background: {theme.PRIMARY};
}}
ads--CFloatingDockContainer {{
    background: {theme.BG_DARK};
    border: 1px solid {theme.BORDER};
}}
"""
