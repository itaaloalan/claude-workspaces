"""Helpers de ícones via qtawesome (FontAwesome 5/6 + Material Design Icons).

Centraliza nomes/cores pra não espalhar string mágica de ícone pelo app.
Uso típico:

    from .icons import ic
    btn.setIcon(ic("fa5s.play"))
    btn.setIcon(ic("fa5s.play", color="#5ac35a"))

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


# Cores default — alinhadas com theme.py / dock_manager QSS
DEFAULT_COLOR = "#c8c8c8"
ACTIVE_COLOR = "#e6e6e6"
MUTED_COLOR = "#9aa0a6"
PRIMARY_COLOR = "#3d6ea8"
SUCCESS_COLOR = "#5ac35a"
WARN_COLOR = "#e5b53b"


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
# atualiza em todo lugar.
ICONS = {
    # IDEs e launchers do header
    "claude": "fa5s.robot",
    "terminal": "fa5s.terminal",
    "pycharm": "mdi6.code-braces",       # genérico pra IDE JetBrains
    "intellij": "mdi6.code-braces",
    "vscode": "mdi6.microsoft-visual-studio-code",
    "rider": "mdi6.code-braces",
    "android_studio": "fa5b.android",
    "webstorm": "mdi6.code-braces",
    "rubymine": "mdi6.code-braces",
    "phpstorm": "mdi6.code-braces",
    # Tabs centrais
    "console": "fa5s.terminal",
    "runners_workspace": "mdi6.source-branch",
    "runners_console": "fa5s.list-alt",
    # Chips do header
    "stack": "fa5s.cube",
    "folder": "fa5s.folder",
    "mcp": "fa5s.plug",
    # Status bar
    "workspace": "fa5s.folder-open",
    "python": "fa5b.python",
    "encoding": "fa5s.file-alt",
    "task_idle": "far.circle",
    "task_active": "fa5s.circle",
    # Sidebar
    "pin": "fa5s.thumbtack",
    "filter": "fa5s.filter",
    "add": "fa5s.plus",
    "chevron_down": "fa5s.chevron-down",
    "chevron_right": "fa5s.chevron-right",
    "more": "fa5s.ellipsis-h",
    "expand": "fa5s.expand",
    "close": "fa5s.times",
    "menu": "fa5s.bars",
}
