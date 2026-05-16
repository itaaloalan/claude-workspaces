"""Views top-level — uma por entrada da ActivityBar.

Cada view é um QWidget self-contained que ocupa a área central da janela
quando ativada. Reutilizam serviços e widgets do app principal mas não
dependem da MainWindow diretamente.
"""

from .catalog_view import CatalogView
from .hooks_view import HooksView
from .mcp_view import McpView

__all__ = ["CatalogView", "HooksView", "McpView"]
