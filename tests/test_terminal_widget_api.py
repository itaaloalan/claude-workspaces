"""Testes de API do TerminalWidget — sem instanciar o widget (sem Qt render).

O objetivo é garantir que renomeações de atributos privados não quebrem
silenciosamente o main_window.py, como aconteceu com _pr_url → _pr_urls
no commit 0.77.0, que causou sessões duplicadas infinitas na sidebar.
"""

import inspect

from claude_workspaces.ui.terminal_widget import (
    TerminalWidget,
    _build_pr_banner_html,
)


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


def test_pr_banner_empty_when_no_urls():
    """Sem URLs → string vazia (caller esconde a barra)."""
    assert _build_pr_banner_html([]) == ""


def test_pr_banner_single_mr():
    """Uma URL GitLab → 'criado' (singular) com 1 link 'MR #N'."""
    html = _build_pr_banner_html(
        ["https://git.example.com/grp/repo/-/merge_requests/1127"]
    )
    assert "criado:" in html
    assert "criados" not in html
    assert html.count("<a ") == 1
    assert "MR #1127" in html


def test_pr_banner_multiple_mrs_lists_all():
    """Várias URLs (sessão multi-pasta) → 'criados' (plural) e um link por MR
    — regressão: o banner do centro só mostrava o último MR detectado."""
    html = _build_pr_banner_html([
        "https://git.example.com/grp/a/-/merge_requests/791",
        "https://git.example.com/grp/b/-/merge_requests/1127",
    ])
    assert "criados:" in html
    assert html.count("<a ") == 2
    assert "MR #791" in html
    assert "MR #1127" in html


def test_pr_banner_uses_all_pr_urls_field():
    """_show_pr_banner deve montar a partir de self._pr_urls (todos), não do
    arg `url` recém-detectado — garante que múltiplos MRs apareçam no centro."""
    src = inspect.getsource(TerminalWidget._show_pr_banner)
    assert "self._pr_urls" in src, (
        "_show_pr_banner deve renderizar self._pr_urls inteiro, não só o url"
    )


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
