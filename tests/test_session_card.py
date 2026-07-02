"""SessionCard não pode emitir QSS inválida.

Regressão do botão ☆ (não-favoritado): a string do meio da concatenação não
era f-string, então o `}}` escapado ia literal pro Qt e invalidava a folha —
"Could not parse stylesheet of object QPushButton(0x…)" re-emitido em todo
polish/hover de todo card não-favoritado (791 ocorrências num app.log).

Captura os warnings do Qt via qInstallMessageHandler durante a construção e
o polish do card e asserta que nenhum parse error aparece.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import qInstallMessageHandler

from claude_workspaces.ui.session_card import SessionCard


class _FakeSession:
    id = "abc123"
    mtime = 0.0
    preview = "sessão de teste"
    origin_cwd = "/tmp"
    path = "x"


@pytest.fixture
def qt_warnings(qapp):
    msgs: list[str] = []
    old = qInstallMessageHandler(lambda _m, _c, text: msgs.append(text))
    yield msgs
    qInstallMessageHandler(old)


def _make_card(qapp, *, fresh: bool) -> SessionCard:
    s = _FakeSession()
    s.mtime = time.time() if fresh else 0.0
    card = SessionCard(s)
    card.show()
    qapp.processEvents()
    return card


def test_unstarred_card_has_valid_stylesheets(qapp, qt_warnings):
    card = _make_card(qapp, fresh=False)  # estado "done" → botão ☆ (não-favoritado)
    bad = [m for m in qt_warnings if "parse stylesheet" in m.lower()]
    assert bad == []
    card.deleteLater()


def test_working_card_has_valid_stylesheets(qapp, qt_warnings):
    card = _make_card(qapp, fresh=True)  # estado "working" → botão Retomar primário
    bad = [m for m in qt_warnings if "parse stylesheet" in m.lower()]
    assert bad == []
    card.deleteLater()
