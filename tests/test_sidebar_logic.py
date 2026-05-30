"""Testes da lógica pura da sidebar (sem Qt) — extraída de main_window.py.

TDD: estes testes foram escritos ANTES de sidebar_logic.py existir, travando
o comportamento que estava embutido em _rebuild_list e _refresh_activity_badges.
"""

from types import SimpleNamespace

from claude_workspaces.models import Workspace
from claude_workspaces.ui.sidebar_logic import (
    count_unseen_by_tab,
    disambiguated_title,
    format_activity_badge,
    partition_workspaces,
    unread_count_for,
)


def _ws(name, pinned=False, minimized=False):
    w = Workspace(name=name, folders=[f"/tmp/{name}"])
    w.pinned = pinned
    w.minimized = minimized
    return w


# ---------- partition_workspaces ----------

def test_partition_empty():
    assert partition_workspaces([]) == ([], [])


def test_partition_all_regular():
    a, b = _ws("a"), _ws("b")
    pinned, regular = partition_workspaces([a, b])
    assert pinned == []
    assert regular == [a, b]


def test_partition_separates_pinned():
    a = _ws("a", pinned=True)
    b = _ws("b")
    pinned, regular = partition_workspaces([a, b])
    assert pinned == [a]
    assert regular == [b]


def test_partition_excludes_minimized_from_both():
    a = _ws("a", pinned=True, minimized=True)
    b = _ws("b", minimized=True)
    c = _ws("c")
    pinned, regular = partition_workspaces([a, b, c])
    assert pinned == []
    assert regular == [c]


def test_partition_preserves_order():
    ws = [_ws("a"), _ws("b", pinned=True), _ws("c"), _ws("d", pinned=True)]
    pinned, regular = partition_workspaces(ws)
    assert [w.name for w in pinned] == ["b", "d"]
    assert [w.name for w in regular] == ["a", "c"]


# ---------- format_activity_badge ----------

def test_badge_zero_total_is_empty():
    badge, tip = format_activity_badge(0, 0)
    assert badge == ""
    assert tip == ""


def test_badge_total_no_working_shows_just_total():
    badge, tip = format_activity_badge(0, 3)
    assert badge == "3"
    assert "3 no total" in tip


def test_badge_with_working_shows_fraction():
    badge, tip = format_activity_badge(2, 5)
    assert badge == "2/5"


def test_badge_tip_describes_working_and_idle():
    _, tip = format_activity_badge(2, 5)
    assert "2 trabalhando" in tip
    assert "3 ocioso" in tip
    assert "5 no total" in tip


def test_badge_all_working():
    badge, _ = format_activity_badge(4, 4)
    assert badge == "4/4"


# ---------- disambiguated_title ----------

def test_disambig_empty_base_returns_base():
    assert disambiguated_title("", 5, [1, 2]) == ""


def test_disambig_single_console_is_first():
    assert disambiguated_title("console", 10, []) == "#1 console"


def test_disambig_oldest_is_one():
    # tab_id menor = mais antigo = #1
    assert disambiguated_title("foo", 1, [1, 5, 9]) == "#1 foo"


def test_disambig_newest_is_last():
    assert disambiguated_title("foo", 9, [1, 5, 9]) == "#3 foo"


def test_disambig_middle_position():
    assert disambiguated_title("foo", 5, [1, 5, 9]) == "#2 foo"


def test_disambig_tab_id_absent_gets_appended():
    # tab_id não na lista de irmãos → entra e é posicionado por ordenação
    assert disambiguated_title("foo", 7, [1, 5]) == "#3 foo"


def test_disambig_dedups_repeated_ids():
    assert disambiguated_title("foo", 5, [1, 5, 5, 9]) == "#2 foo"


# ---------- count_unseen_by_tab ----------

def _notif(tab_id):
    return SimpleNamespace(tab_id=tab_id)


def test_count_unseen_empty():
    assert count_unseen_by_tab([]) == {}


def test_count_unseen_groups_by_tab():
    notifs = [_notif(1), _notif(1), _notif(2)]
    assert count_unseen_by_tab(notifs) == {1: 2, 2: 1}


def test_count_unseen_ignores_none_tab():
    notifs = [_notif(None), _notif(5), _notif(None)]
    assert count_unseen_by_tab(notifs) == {5: 1}


# ---------- unread_count_for ----------

def test_unread_count_uses_session_when_present():
    sess = {"sid-a": 4}
    tabs = {10: 1}
    assert unread_count_for("sid-a", 10, sess, tabs) == 4  # max(4, 1)


def test_unread_count_uses_tab_when_higher():
    sess = {"sid-a": 1}
    tabs = {10: 7}
    assert unread_count_for("sid-a", 10, sess, tabs) == 7


def test_unread_count_no_session_id_falls_back_to_tab():
    assert unread_count_for(None, 10, {"sid-a": 99}, {10: 3}) == 3


def test_unread_count_zero_when_absent():
    assert unread_count_for("sid-x", 10, {}, {}) == 0
