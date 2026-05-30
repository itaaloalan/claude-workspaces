"""Fixtures compartilhadas para toda a suite de testes.

O qapp de sessão garante que só uma QApplication existe durante todo o
processo de testes — evita o overhead de criar/destruir uma por módulo
e o crash que ocorre quando dois módulos criam QApplication em paralelo.
"""

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def tmp_workspaces(tmp_path, monkeypatch):
    """Redireciona load/save de workspaces para tmp_path.

    Impede que testes poluam ~/.config/claude-workspaces/workspaces.json.
    """
    from claude_workspaces import storage

    f = tmp_path / "workspaces.json"
    monkeypatch.setattr(storage, "workspaces_file", lambda: f)
    monkeypatch.setattr(storage, "config_dir", lambda: tmp_path)
    return f
