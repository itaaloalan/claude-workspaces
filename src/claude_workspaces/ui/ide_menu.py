"""Menu de seleção de IDE × pasta pro dropdown do botão "VS Code".

Compartilhado entre o chip do header do console (main_window) e o botão do
canto central do workspace (workspace_details). Monta um QMenu que deixa o
usuário escolher qual(is) pasta(s) abrir e em qual IDE (VS Code, PyCharm,
WebStorm, IntelliJ, Rider).
"""

from collections.abc import Callable

from PySide6.QtWidgets import QMenu, QWidget

from ..launchers import IDE_LABEL

# Ordem de exibição das IDEs nos submenus.
_IDE_ORDER: list[str] = ["vscode", "pycharm", "webstorm", "intellij", "rider"]


def build_ide_menu(
    parent: QWidget,
    targets: list[tuple[str, str]],
    on_open: Callable[[str, list[str]], None],
) -> QMenu:
    """Cria o menu de seleção. `targets` = [(label, path)]. `on_open` recebe
    (ide_key, lista_de_paths). Retorna QMenu vazio se não houver alvos."""
    menu = QMenu(parent)
    if not targets:
        return menu

    all_paths = [p for _label, p in targets]

    if len(targets) > 1:
        sub = menu.addMenu("Abrir todos")
        _add_ide_actions(sub, all_paths, on_open)
        menu.addSeparator()

    for label, path in targets:
        sub = menu.addMenu(label)
        _add_ide_actions(sub, [path], on_open)

    return menu


def _add_ide_actions(
    menu: QMenu,
    paths: list[str],
    on_open: Callable[[str, list[str]], None],
) -> None:
    for ide_key in _IDE_ORDER:
        act = menu.addAction(IDE_LABEL[ide_key])
        act.triggered.connect(
            lambda _checked=False, k=ide_key, p=list(paths): on_open(k, p)
        )
