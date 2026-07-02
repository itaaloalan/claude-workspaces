"""Política de entrega do DesktopNotifierAdapter.

Testa o adapter com um DesktopNotifier fake (grava as chamadas notify/close),
cobrindo: estados de atenção (Aguardando/Decisão) entregues como resident/
sem-timeout; kinds informativos (Trabalhando/Concluído/Execução-longa) NUNCA
viram popup nativo — ficam só na central in-app; a transição working→aguardando
entrega o banner de Aguardando; avisos não-atenção seguem auto-dismiss; update
sem mudança visual é pulado; e mark_seen fecha o popup.
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
    """Espelha a API assíncrona do DesktopNotifier: resolve o
    replaces_id_provider no "run" e entrega o note_id via on_posted inline
    (síncrono — nos testes não há pool)."""

    def __init__(self):
        self.notify_calls: list[dict] = []
        self.close_calls: list[int] = []
        self._next = 0

    @property
    def available(self) -> bool:
        return True

    def notify(self, **kw) -> None:
        self._next += 1
        provider = kw.pop("replaces_id_provider", None)
        kw["replaces_id"] = int(provider()) if provider else int(kw.get("replaces_id", 0))
        on_posted = kw.pop("on_posted", None)
        self.notify_calls.append(kw)
        if on_posted is not None:
            on_posted(self._next)

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


def test_working_popup_is_muted(setup):
    # "Comecei a trabalhar" não interrompe: entrada existe na central,
    # mas nenhum popup nativo é emitido.
    svc, fake, _ = setup
    n = svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
                   dedup_key=KEY, tab_id=1)
    assert n is not None  # central in-app registra normalmente
    assert fake.notify_calls == []


def test_task_completed_and_long_running_popups_muted(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.TASK_COMPLETED, "✓ Sessão encerrada — w",
               dedup_key="task:w:1", tab_id=1)
    svc.notify(NotificationKind.LONG_RUNNING, "⏱ Execução longa — w",
               dedup_key="long:w:1", tab_id=1)
    assert fake.notify_calls == []


def test_waiting_is_resident_no_timeout(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 1
    call = fake.notify_calls[0]
    assert call["resident"] is True
    assert call["timeout_ms"] == 0


def test_transition_working_to_waiting_delivers_waiting(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WORKING, "⚙ Trabalhando — w",
               dedup_key=KEY, tab_id=1)
    # working → aguardando (mesmo dedup, dentro do cooldown → changed):
    # o Trabalhando foi mudo, mas o Aguardando PRECISA aparecer.
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 1
    upd = fake.notify_calls[0]
    assert upd["resident"] is True
    assert upd["timeout_ms"] == 0
    assert "Aguardando" in upd["title"]


def test_decision_is_resident_no_timeout(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.PERMISSION_REQUIRED, "❓ Decisão — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 1
    call = fake.notify_calls[0]
    assert call["resident"] is True
    assert call["timeout_ms"] == 0


def test_non_attention_kind_still_autodismiss(setup):
    svc, fake, _ = setup
    # Aviso não-atenção que ainda popa (falha) NÃO deve virar fixo.
    svc.notify(NotificationKind.TASK_FAILED, "✗ Sessão falhou — w",
               dedup_key="task:w:1", tab_id=1)
    assert len(fake.notify_calls) == 1
    call = fake.notify_calls[0]
    assert call["resident"] is False
    assert call["timeout_ms"] > 0


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
    n = svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
                   dedup_key=KEY, tab_id=1)
    assert n is not None
    svc.mark_seen(n.id)
    assert fake.close_calls == [1]


def test_transition_replaces_same_banner(setup):
    svc, fake, _ = setup
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    # Aguardando → Decisão no mesmo console: precisa REUSAR o banner
    # (replaces_id do primeiro), não empilhar um segundo.
    svc.notify(NotificationKind.PERMISSION_REQUIRED, "❓ Decisão — w",
               dedup_key=KEY, tab_id=1)
    assert len(fake.notify_calls) == 2
    assert fake.notify_calls[0]["replaces_id"] == 0
    assert fake.notify_calls[1]["replaces_id"] == 1


def test_posted_after_seen_closes_banner(tmp_path: Path):
    """Corrida do notify assíncrono: o usuário foca o console (mark_seen)
    enquanto o gdbus ainda roda. Quando o note_id chega, o adapter deve
    FECHAR o banner em vez de registrá-lo como ativo."""
    svc = NotificationService(tmp_path / "n.json")
    svc.set_preferences(cooldown_seconds=60, desktop_enabled=True)

    class _DeferredDesktop(_FakeDesktop):
        def __init__(self):
            super().__init__()
            self.pending_posted = []

        def notify(self, **kw) -> None:
            self._next += 1
            kw.pop("replaces_id_provider", None)
            self.pending_posted.append((kw.pop("on_posted", None), self._next))
            self.notify_calls.append(kw)

    fake = _DeferredDesktop()
    adapter = DesktopNotifierAdapter(svc, fake, is_app_focused=lambda: False)
    n = svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
                   dedup_key=KEY, tab_id=1)
    assert n is not None and fake.pending_posted
    svc.mark_seen(n.id)  # usuário viu antes do servidor responder
    on_posted, nid = fake.pending_posted.pop()
    on_posted(nid)
    assert fake.close_calls == [nid]
    assert adapter._active == {}


def test_waiting_suppressed_when_target_visible(tmp_path: Path):
    svc = NotificationService(tmp_path / "n.json")
    svc.set_preferences(cooldown_seconds=60, desktop_enabled=True)
    fake = _FakeDesktop()
    DesktopNotifierAdapter(
        svc, fake,
        is_app_focused=lambda: False,
        is_target_visible=lambda n: True,  # usuário olhando o console
    )
    svc.notify(NotificationKind.AGENT_WAITING, "⏳ Aguardando — w",
               dedup_key=KEY, tab_id=1)
    assert fake.notify_calls == []  # não popa enquanto o console está visível
