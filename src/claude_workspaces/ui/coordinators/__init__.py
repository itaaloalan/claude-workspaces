"""Coordinators — encapsulam responsabilidades antes espalhadas
na MainWindow.

Cada coordinator possui um conjunto de estado + lógica. A MainWindow
vira composição: instancia os coordinators, wira signals entre eles
e a UI, e delega CRUD/ações.

Padrão: cada coordinator é um QObject com signals que emitem mudanças
de estado. A UI escuta e reage. Não há circular dependency — coordinators
podem chamar outros via referência (passada no construtor) mas não via
signal loops.
"""

from .dock_coordinator import DockCoordinator
from .launch_coordinator import LaunchCoordinator
from .plugin_coordinator import PluginCoordinator
from .terminal_coordinator import TerminalCoordinator
from .workspace_coordinator import WorkspaceCoordinator

__all__ = [
    "DockCoordinator",
    "LaunchCoordinator",
    "PluginCoordinator",
    "TerminalCoordinator",
    "WorkspaceCoordinator",
]
