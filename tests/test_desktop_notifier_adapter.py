"""Notificação fixa 'Trabalhando' → atualiza in-place pro estado seguinte.

Testa o DesktopNotifierAdapter com um DesktopNotifier fake (grava as chamadas
notify/close), cobrindo: AGENT_WORKING entregue como resident/sem-timeout; a
transição working→aguardando re-entrega no MESMO banner (replaces_id) e auto-
dismiss; update sem mudança visual é pulado; e mark_seen fecha o popup.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from claude_workspaces.notifications import (
    NotificationKind,
    NotificationService,
)
from claude_workspaces.notifications.desktop import DesktopNotifierAdapter


class _FakeDesktop:
    def __init__(self):
        self.notify_calls: list[dict] = []
        self.close_calls: list[int] = []
        self._next = 0

    @property
    def available(self) -> bool:
        return True

    def notify(self, **kw) -> int:
        self._next += 1
        self.notify_calls.append(kw)
        return self._next

    def close(self, note_id: int) -> None:
        self.close_calls.append(note_id)


@pytest.fixture
def setup(tmp_path: Path):
    svc = NotificationService(tmp_path / "n.json")
    svc.set_preferences(cooldown_seconds=60, desktop_enabled=True)
    fake = _FakeDesktop()
    adapter = DesktopNotifierAdapter(svc, fake, is_app_focused=lambda: False)
    return svc, fake, adapter


KEY = "agent:w:1"


def test_working_is_resident_no_timeout(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 1
    call = fake.notify_calls[0]
    assert call["resident"] is True
    assert call["timeout_ms"] == 0


def test_transition_updates_same_banner_and_autodismiss(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
               dedup_key=KEY, tab_id=1)
    first_id = fake.notify_calls[0]  # nid 1
    # working → aguardando (mesmo dedup, dentro do cooldown → changed)
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 2
    upd = fake.notify_calls[1]
    assert upd["replaces_id"] == 1          # mesmo banner
    assert upd["resident"] is False          # agora auto-dismiss
    assert "Aguardando" in upd["title"]


def test_noop_update_is_skipped(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    # mesmíssimo conteúdo de novo → changed sem mudança visual → não re-emite
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 1


def test_mark_seen_closes_popup(setup):
    svc, fake, _ = setup
    n = svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
                   dedup_key=KEY, tab_id=1)
    assert n is not None
    svc.mark_seen(n.id)
    assert fake.close_calls == [1]


def test_working_suppressed_when_target_visible(tmp_path: Path):
    svc = NotificationService(tmp_path / "n.json")
    svc.set_preferences(cooldown_seconds=60, desktop_enabled=True)
    fake = _FakeDesktop()
    DesktopNotifierAdapter(
        svc, fake,
        is_app_focused=lambda: False,
        is_target_visible=lambda n: True,  # usuário olhando o console
    )
    svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
               dedup_key=KEY, tab_id=1)
    assert fake.notify_calls == []  # não popa enquanto o console está visível
