from claude_workspaces.ui.terminal_state import TerminalState


def test_default_empty():
    s = TerminalState()
    assert s.tree_items == {}
    assert s.activity == {}
    assert s.inbox == {}
    assert s.running_counts == {}
    assert s.any_working() is False


def test_release_tab_clears_all():
    s = TerminalState()
    s.tree_items[42] = object()
    s.activity[42] = ("status", True, "title")
    s.inbox[42] = {"workspace_id": "w"}
    inbox_changed = s.release_tab(42)
    assert inbox_changed is True
    assert 42 not in s.tree_items
    assert 42 not in s.activity
    assert 42 not in s.inbox


def test_release_tab_no_inbox():
    s = TerminalState()
    s.tree_items[42] = object()
    s.activity[42] = ("", False, "t")
    inbox_changed = s.release_tab(42)
    assert inbox_changed is False


def test_release_tab_unknown_id_is_safe():
    s = TerminalState()
    assert s.release_tab(999) is False


def test_any_working_reflects_state():
    s = TerminalState()
    s.activity[1] = ("idle", False, "t")
    assert s.any_working() is False
    s.activity[2] = ("trabalhando", True, "t")
    assert s.any_working() is True
    s.release_tab(2)
    assert s.any_working() is False


def test_running_counts_setter_removes_zero():
    s = TerminalState()
    s.set_running_count("ws1", 3)
    assert s.running_count_of("ws1") == 3
    s.set_running_count("ws1", 0)
    assert "ws1" not in s.running_counts
    assert s.running_count_of("ws1") == 0


def test_running_counts_negative_treated_as_zero():
    s = TerminalState()
    s.set_running_count("ws", -1)
    assert "ws" not in s.running_counts
