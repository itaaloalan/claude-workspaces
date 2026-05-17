"""Builders — funções/classes que constroem partes da UI antes
inflavam o `_build_ui` da MainWindow.

Cada builder devolve o widget construído e expõe attrs nomeados pra
que a MainWindow possa wirar signals.
"""

from .sidebar_builder import SidebarBuilder
from .terminal_pane_builder import TerminalPaneBuilder

__all__ = ["SidebarBuilder", "TerminalPaneBuilder"]
