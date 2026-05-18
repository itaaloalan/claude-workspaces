"""ShortcutsInstaller — instala todos os QShortcuts da MainWindow.

Antes era um método `_install_shortcuts` de ~60 linhas. Foi extraído pra
manter o construtor da MainWindow legível e centralizar o mapa de atalhos
num lugar só (facilita auditar conflitos e exibir no ShortcutsDialog).
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut

from ..activity_bar import (
    VIEW_APPS,
    VIEW_CATALOG,
    VIEW_HOOKS,
    VIEW_MCP,
    VIEW_PLUGINS,
    VIEW_WORKSPACES,
)


def install_shortcuts(mw) -> None:
    """Instala todos os QShortcuts da MainWindow.

    `mw` é a MainWindow — usamos duck-typing pra evitar import circular.
    """
    # Layout
    QShortcut(QKeySequence("Ctrl+B"), mw, mw._toggle_sidebar)
    QShortcut(QKeySequence("Ctrl+J"), mw, mw._toggle_terminal)
    QShortcut(QKeySequence("Ctrl+Shift+B"), mw, mw._toggle_right_dock)
    # Workspace
    QShortcut(QKeySequence("Ctrl+Return"), mw, mw._launch_current_claude)
    QShortcut(QKeySequence("Ctrl+,"), mw, mw._show_settings)
    QShortcut(QKeySequence("Ctrl+N"), mw, mw.add_workspace)
    for i in range(1, 10):
        QShortcut(
            QKeySequence(f"Ctrl+{i}"),
            mw,
            lambda idx=i - 1: mw._jump_to_workspace(idx),
        )
    QShortcut(QKeySequence("Ctrl+Tab"), mw, lambda: mw._cycle_workspace(1))
    QShortcut(QKeySequence("Ctrl+Shift+Tab"), mw, lambda: mw._cycle_workspace(-1))
    # Terminal
    QShortcut(QKeySequence("Ctrl+T"), mw, mw._new_terminal_tab)
    QShortcut(QKeySequence("Ctrl+Shift+W"), mw, mw._close_active_terminal_tab)
    QShortcut(QKeySequence("Ctrl+K"), mw, mw._clear_active_terminal)
    QShortcut(QKeySequence("Ctrl+Alt+Right"), mw, lambda: mw._cycle_terminal_tab(1))
    QShortcut(QKeySequence("Ctrl+Alt+Left"), mw, lambda: mw._cycle_terminal_tab(-1))
    # Arquivos
    QShortcut(QKeySequence("Ctrl+P"), mw, mw._quick_open_file)
    QShortcut(QKeySequence("Ctrl+O"), mw, mw._open_folder_in_file_manager)
    QShortcut(QKeySequence("Ctrl+Shift+C"), mw, mw._copy_primary_folder)
    # Resume da última sessão
    QShortcut(QKeySequence("Ctrl+Shift+R"), mw, mw._resume_last_session)
    # Busca em sessões
    QShortcut(QKeySequence("Ctrl+Shift+F"), mw, mw._show_sessions_search)
    # Views (activity bar) — Ctrl+Shift+1..4 (Ctrl+1..9 já é workspace jump)
    QShortcut(
        QKeySequence("Ctrl+Shift+1"), mw,
        lambda: mw.activity_bar.activate(VIEW_WORKSPACES),
    )
    QShortcut(
        QKeySequence("Ctrl+Shift+2"), mw,
        lambda: mw.activity_bar.activate(VIEW_CATALOG),
    )
    QShortcut(
        QKeySequence("Ctrl+Shift+3"), mw,
        lambda: mw.activity_bar.activate(VIEW_HOOKS),
    )
    QShortcut(
        QKeySequence("Ctrl+Shift+4"), mw,
        lambda: mw.activity_bar.activate(VIEW_MCP),
    )
    QShortcut(
        QKeySequence("Ctrl+Shift+5"), mw,
        lambda: mw.activity_bar.activate(VIEW_PLUGINS),
    )
    QShortcut(
        QKeySequence("Ctrl+Shift+6"), mw,
        lambda: mw.activity_bar.activate(VIEW_APPS),
    )
    # Paleta de comandos de plugins (analog do Ctrl+Shift+P do VS Code;
    # Ctrl+P já é Quick Open de arquivo, linha 50)
    QShortcut(QKeySequence("Ctrl+Shift+P"), mw, mw._open_plugin_palette)
    # Help
    QShortcut(QKeySequence("Ctrl+/"), mw, mw._show_shortcuts)
    QShortcut(QKeySequence("F1"), mw, mw._show_shortcuts)
