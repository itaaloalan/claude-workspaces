"""Testes de API do TerminalWidget — sem instanciar o widget (sem Qt render).

O objetivo é garantir que renomeações de atributos privados não quebrem
silenciosamente o main_window.py, como aconteceu com _pr_url → _pr_urls
no commit 0.77.0, que causou sessões duplicadas infinitas na sidebar.
"""

import inspect

from claude_workspaces.ui.terminal_widget import TerminalWidget


def test_pr_urls_is_list_field_not_singular():
    """_pr_url (singular) não deve existir no __init__ — regressão do bug
    de sessões infinitas (main_window.py:4989 AttributeError silenciado)."""
    src = inspect.getsource(TerminalWidget.__init__)
    assert "_pr_urls" in src, "_pr_urls deve existir no __init__"
    assert "_pr_url:" not in src, (
        "_pr_url (singular) não deve existir — main_window.py usa _pr_urls"
    )


def test_set_detected_pr_url_exists():
    """Método set_detected_pr_url deve existir (usado pelo PrStatusPoller)."""
    assert hasattr(TerminalWidget, "set_detected_pr_url")
    assert callable(TerminalWidget.set_detected_pr_url)


def test_pr_detected_signal_exists():
    """Signal pr_detected deve existir (conectado no _wire_child_actions)."""
    assert hasattr(TerminalWidget, "pr_detected")


def test_main_window_uses_pr_urls_not_pr_url():
    """main_window.py não deve referenciar term._pr_url (singular).

    Regressão: se alguém reintroduzir `term._pr_url` em _add_terminal_child,
    o AttributeError é silenciado pelo Qt e tree_items nunca é atualizado,
    causando duplicação infinita de sessões na sidebar.
    """
    import pathlib
    import re
    mw_path = (
        pathlib.Path(__file__).parent.parent
        / "src/claude_workspaces/ui/main_window.py"
    )
    src = mw_path.read_text()
    # Usa lookahread negativo pra não confundir "_pr_url" com "_pr_urls"
    match = re.search(r"term\._pr_url(?!s)", src)
    assert match is None, (
        f"main_window.py linha contém term._pr_url (singular) na posição "
        f"{match.start()}: use term._pr_urls (list) — "
        "veja bug de sessões infinitas introduzido em 0.77.0"
    )
