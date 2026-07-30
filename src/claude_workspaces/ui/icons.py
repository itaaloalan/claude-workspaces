"""Helpers de ícones via qtawesome (FontAwesome 5/6 + Material Design Icons).

Centraliza nomes/cores pra não espalhar string mágica de ícone pelo app.
Uso típico:

    from .icons import ic
    btn.setIcon(ic("fa5s.play"))
    btn.setIcon(ic("fa5s.play", color="#6fbf73"))

Se o qtawesome não estiver disponível ou o nome do ícone for inválido,
retorna QIcon() vazio (não quebra a UI — só não desenha).
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

try:
    import qtawesome as qta
    _HAS_QTA = True
except ImportError:  # pragma: no cover — opcional na primeira inicialização
    _HAS_QTA = False


# Cores default — tokens do theme.py (monocromático; cor saturada só
# em status semântico)
from . import theme as _theme

DEFAULT_COLOR = _theme.TEXT_MUTED
ACTIVE_COLOR = _theme.TEXT_PRIMARY
MUTED_COLOR = _theme.TEXT_FAINT
PRIMARY_COLOR = _theme.PRIMARY
SUCCESS_COLOR = _theme.SUCCESS
WARN_COLOR = _theme.WARNING


def ic(name: str, color: str = DEFAULT_COLOR, size: int | None = None) -> QIcon:
    """Wrapper sobre qtawesome.icon com defaults sensatos.

    Args:
        name: nome do ícone no formato 'prefixo.nome', ex.: 'fa5s.play',
              'mdi6.folder-outline'. Veja qtawesome docs pros prefixos
              disponíveis (fa5s, fa5b, fa6s, fa6b, mdi, mdi6, ph).
        color: cor em hex ou nome. Default: cinza claro.
        size: ignorado aqui (QIcon escala via setIconSize do widget).
    """
    if not _HAS_QTA:
        return QIcon()
    try:
        return qta.icon(name, color=color)
    except Exception:
        return QIcon()


# Catálogo de ícones do app — fonte única da verdade. Trocar aqui
# atualiza em todo lugar. Set principal: Phosphor (`ph.`) — traço fino,
# estética Orca. fa5b/mdi6 só pra marcas sem equivalente.
ICONS = {
    # IDEs e launchers do header
    "claude": "ph.robot",
    "terminal": "ph.terminal-window",
    "pycharm": "ph.brackets-curly",       # genérico pra IDE JetBrains
    "intellij": "ph.brackets-curly",
    "vscode": "mdi6.microsoft-visual-studio-code",
    "rider": "ph.brackets-curly",
    "android_studio": "ph.android-logo",
    "webstorm": "ph.brackets-curly",
    "rubymine": "ph.brackets-curly",
    "phpstorm": "ph.brackets-curly",
    # Tabs centrais
    "console": "ph.terminal-window",
    "runners_workspace": "ph.git-branch",
    "runners_console": "ph.list",
    # Chips do header
    "stack": "ph.stack",
    "folder": "ph.folder",
    "mcp": "ph.share-network",
    # Status bar
    "workspace": "ph.folder-open",
    "python": "fa5b.python",
    "encoding": "ph.file-text",
    "task_idle": "ph.circle",
    "task_active": "ph.circle-fill",
    # Sidebar
    "pin": "ph.push-pin",
    "filter": "ph.funnel",
    "add": "ph.plus",
    "chevron_down": "ph.caret-down",
    "chevron_right": "ph.caret-right",
    "more": "ph.dots-three",
    "expand": "ph.arrows-out-simple",
    "close": "ph.x",
    "menu": "ph.list",
}
