"""Testes do núcleo de notificações.

Cobertura mínima exigida no refactor:
- criação, deduplicação, cooldown, marcar como lida, adiar, filtros,
  persistência e JSON inválido.

NotificationStore é testado sem Qt. NotificationService precisa de
QCoreApplication (sinais), então usa fixture global.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from claude_workspaces.notifications import (
    Notification,
    NotificationKind,
    NotificationPriority,
    NotificationService,
    NotificationStore,
    persistence,
)

# ---------------------------------------------------------------------- Store


def _make(**kw):
    return Notification.make(
        kind=kw.get("kind", NotificationKind.AGENT_WAITING),
        title=kw.get("title", "t"),
        body=kw.get("body", "b"),
        workspace_id=kw.get("workspace_id", "ws1"),
        session_id=kw.get("session_id", "s1"),
        priority=kw.get("priority"),
        dedup_key=kw.get("dedup_key"),
    )


def test_store_add_and_list():
    s = NotificationStore()
    s.add(_make(title="A"))
    s.add(_make(title="B", workspace_id="ws2", dedup_key="x"))
    items = s.list()
    assert len(items) == 2
    assert {n.title for n in items} == {"A", "B"}


def test_store_filter_by_workspace():
    s = NotificationStore()
    s.add(_make(workspace_id="ws1"))
    s.add(_make(workspace_id="ws2", dedup_key="k2"))
    assert len(s.list(workspace_id="ws1")) == 1
    assert len(s.list(workspace_id="ws2")) == 1


def test_store_filter_only_actionable():
    s = NotificationStore()
    s.add(_make(kind=NotificationKind.TASK_COMPLETED, dedup_key="a"))
    s.add(_make(kind=NotificationKind.PERMISSION_REQUIRED, dedup_key="b"))
    s.add(_make(kind=NotificationKind.AGENT_IDLE, dedup_key="c"))
    items = s.list(only_actionable=True)
    kinds = {n.kind for n in items}
    assert NotificationKind.PERMISSION_REQUIRED in kinds
    assert NotificationKind.TASK_COMPLETED not in kinds


def test_store_mark_seen_and_unread_count():
    s = NotificationStore()
    a = s.add(_make(dedup_key="a"))
    b = s.add(_make(dedup_key="b"))
    assert s.unread_count() == 2
    s.mark_seen(a.id)
    assert s.unread_count() == 1
    s.mark_seen(b.id)
    assert s.unread_count() == 0


def test_store_snooze_makes_pending_skip_reminder():
    s = NotificationStore()
    n = s.add(_make(kind=NotificationKind.AGENT_WAITING))
    assert n in s.actionable_pending()
    s.snooze(n.id, 60)
    assert s.get(n.id).is_snoozed()
    assert n.id not in {p.id for p in s.actionable_pending()}


def test_store_dismiss_excludes_from_default_list():
    s = NotificationStore()
    n = s.add(_make())
    s.dismiss(n.id)
    assert s.list() == []
    assert len(s.list(include_dismissed=True)) == 1


def test_store_history_limit_evicts_oldest():
    s = NotificationStore(history_limit=10)
    for i in range(15):
        n = _make(dedup_key=f"k{i}")
        n.updated_at = float(i)
        s.add(n)
    items = s.snapshot()
    assert len(items) == 10
    # mantém os mais recentes (updated_at 5..14)
    assert min(n.updated_at for n in items) == 5.0


# ------------------------------------------------------------------- Service


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    """QCoreApplication é necessário pros sinais Qt em NotificationService."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_service_notify_creates_entry(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    n = svc.notify(
        NotificationKind.TASK_COMPLETED, "t", "b",
        workspace_id="ws1", session_id="s1",
    )
    assert n is not None
    assert n.kind == NotificationKind.TASK_COMPLETED
    assert n.workspace_id == "ws1"
    assert svc.unread_count() == 1


def test_service_dedup_within_cooldown_does_not_double(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.set_preferences(cooldown_seconds=60)
    a = svc.notify(NotificationKind.AGENT_WAITING, "x", workspace_id="w", session_id="s")
    b = svc.notify(NotificationKind.AGENT_WAITING, "x2", workspace_id="w", session_id="s")
    assert a is not None and b is not None
    assert a.id == b.id, "dedup deve atualizar a mesma entrada"
    assert b.occurrences == 2
    assert len(svc.list()) == 1


def test_service_cooldown_expired_emits_added_again(tmp_path: Path, monkeypatch):
    svc = NotificationService(tmp_path / "notif.json")
    svc.set_preferences(cooldown_seconds=1)
    added = []
    changed = []
    svc.notification_added.connect(lambda n: added.append(n))
    svc.notification_changed.connect(lambda n: changed.append(n))

    a = svc.notify(NotificationKind.AGENT_WAITING, "x", workspace_id="w")
    assert a is not None
    # primeiro emit é "added"
    assert len(added) == 1
    # força updated_at antigo
    svc.get(a.id).updated_at = time.time() - 10.0
    b = svc.notify(NotificationKind.AGENT_WAITING, "x", workspace_id="w")
    assert b is not None and b.id == a.id
    # fora do cooldown → reemite como added (re-popup permitido)
    assert len(added) == 2


def test_service_mark_seen_decreases_unread(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    n = svc.notify(NotificationKind.TASK_COMPLETED, "t", workspace_id="w")
    assert svc.unread_count() == 1
    svc.mark_seen(n.id)
    assert svc.unread_count() == 0


def test_service_snooze_hides_from_reminder(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    n = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w")
    svc.snooze(n.id, 60)
    fired = []
    svc.reminder_due.connect(lambda x: fired.append(x))
    svc._tick_reminders()
    assert fired == []


def test_service_filter_by_workspace_and_kind(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.notify(NotificationKind.AGENT_WAITING, "a", workspace_id="w1", session_id="s1")
    svc.notify(NotificationKind.TASK_FAILED, "b", workspace_id="w1", session_id="s2")
    svc.notify(NotificationKind.AGENT_IDLE, "c", workspace_id="w2", session_id="s3")
    assert len(svc.list(workspace_id="w1")) == 2
    assert len(svc.list(kind=NotificationKind.TASK_FAILED)) == 1


def test_service_muted_kind_is_silenced(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.set_preferences(muted_kinds=[NotificationKind.AGENT_IDLE])
    n = svc.notify(NotificationKind.AGENT_IDLE, "t", workspace_id="w")
    assert n is None
    assert svc.list() == []


def test_service_muted_workspace_is_silenced(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.set_preferences(muted_workspaces=["w-mute"])
    a = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w-mute")
    b = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w-ok")
    assert a is None and b is not None


def test_service_workspace_silencer_suppresses_notify(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.set_workspace_silencer(lambda ws_id: ws_id == "w-min")
    added = []
    svc.notification_added.connect(lambda n: added.append(n))
    a = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w-min")
    b = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w-ok")
    assert a is None, "workspace silenciado nem cria a entrada"
    assert b is not None
    assert len(added) == 1
    assert svc.list(workspace_id="w-min") == []


def test_service_workspace_silencer_skips_reminders(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    n = svc.notify(NotificationKind.AGENT_WAITING, "t", workspace_id="w1")
    assert n is not None
    # Workspace minimizado depois da notificação criada: reminder não dispara.
    svc.set_workspace_silencer(lambda ws_id: ws_id == "w1")
    svc._last_reminder[n.id] = 0.0  # força "já passou do intervalo"
    fired = []
    svc.reminder_due.connect(lambda x: fired.append(x))
    svc._tick_reminders()
    assert fired == []
    # Restaurado → reminder volta a disparar.
    svc.set_workspace_silencer(None)
    svc._tick_reminders()
    assert len(fired) == 1


def test_service_unread_by_workspace_and_session(tmp_path: Path):
    svc = NotificationService(tmp_path / "notif.json")
    svc.notify(NotificationKind.AGENT_WAITING, "a", workspace_id="w1", session_id="s1")
    svc.notify(NotificationKind.TASK_FAILED, "b", workspace_id="w1", session_id="s2")
    svc.notify(NotificationKind.AGENT_IDLE, "c", workspace_id="w2", session_id="s3")
    assert svc.unread_by_workspace() == {"w1": 2, "w2": 1}
    assert svc.unread_by_session() == {"s1": 1, "s2": 1, "s3": 1}


# --------------------------------------------------------------- Persistência


def test_persistence_roundtrip(tmp_path: Path):
    path = tmp_path / "notif.json"
    svc1 = NotificationService(path)
    n = svc1.notify(NotificationKind.PERMISSION_REQUIRED, "perm", workspace_id="w")
    svc1.set_preferences(muted_kinds=[NotificationKind.AGENT_IDLE])
    # reload em nova instância
    svc2 = NotificationService(path)
    assert len(svc2.list()) == 1
    assert svc2.list()[0].id == n.id
    assert svc2.preferences["muted_kinds"] == [NotificationKind.AGENT_IDLE]


def test_persistence_missing_file_is_ok(tmp_path: Path):
    path = tmp_path / "does-not-exist.json"
    svc = NotificationService(path)
    assert svc.list() == []
    assert svc.unread_count() == 0


def test_persistence_corrupt_json_archives_and_recovers(tmp_path: Path):
    path = tmp_path / "notif.json"
    path.write_text("{not valid json", encoding="utf-8")
    svc = NotificationService(path)
    # estado default + backup criado
    assert svc.list() == []
    backups = list(tmp_path.glob("notif.json.corrupt-*"))
    assert backups, "deve criar backup do JSON corrompido"
    # app continua funcionando — pode emitir e persistir
    svc.notify(NotificationKind.TASK_COMPLETED, "ok", workspace_id="w")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == persistence.SCHEMA_VERSION


def test_persistence_wrong_shape_archives(tmp_path: Path):
    path = tmp_path / "notif.json"
    # JSON válido mas com schema errado (lista no topo)
    path.write_text("[1,2,3]", encoding="utf-8")
    svc = NotificationService(path)
    assert svc.list() == []
    assert list(tmp_path.glob("notif.json.corrupt-*"))


def test_priority_default_for_permission_required():
    n = Notification.make(NotificationKind.PERMISSION_REQUIRED, "t")
    assert n.priority == NotificationPriority.CRITICAL


def test_priority_to_urgency_mapping():
    assert NotificationPriority.to_urgency(NotificationPriority.LOW) == 0
    assert NotificationPriority.to_urgency(NotificationPriority.NORMAL) == 1
    assert NotificationPriority.to_urgency(NotificationPriority.HIGH) == 2
    assert NotificationPriority.to_urgency(NotificationPriority.CRITICAL) == 2
