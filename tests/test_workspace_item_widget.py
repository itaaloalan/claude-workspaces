"""Testes do WorkspaceItemWidget — widget top-level da sidebar."""

import pytest

from claude_workspaces.ui.workspace_item_widget import WorkspaceItemWidget


@pytest.fixture
def widget_and_calls(qapp):
    calls = {}

    def on_add():
        calls["add"] = calls.get("add", 0) + 1

    def on_collapse():
        calls["collapse"] = True

    def on_pin():
        calls["pin"] = True

    def on_minimize():
        calls["minimize"] = True

    w = WorkspaceItemWidget(
        "Meu Projeto",
        on_add_claude=on_add,
        on_toggle_collapse=on_collapse,
        on_toggle_pin=on_pin,
        on_minimize=on_minimize,
    )
    return w, calls


# ---------- construção ----------

def test_label_shows_name(widget_and_calls):
    w, _ = widget_and_calls
    assert w._label.text() == "Meu Projeto"


def test_initial_dot_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._dot.isHidden()


def test_initial_badge_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._badge.isHidden()


def test_initial_notif_badge_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._notif_badge.isHidden()


def test_initial_runner_badge_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._runner_badge.isHidden()


def test_initial_pin_icon_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._pin_icon.isHidden()


def test_initial_not_selected(widget_and_calls):
    w, _ = widget_and_calls
    assert w._selected is False


# ---------- set_running_count ----------

def test_running_count_zero_hides_indicators(widget_and_calls):
    w, _ = widget_and_calls
    w.set_running_count(1)
    w.set_running_count(0)
    assert w._dot.isHidden()
    assert w._badge.isHidden()


def test_running_count_one_shows_dot_hides_badge(widget_and_calls):
    w, _ = widget_and_calls
    w.set_running_count(1)
    assert not w._dot.isHidden()
    assert w._badge.isHidden()


def test_running_count_two_shows_dot_and_badge(widget_and_calls):
    w, _ = widget_and_calls
    w.set_running_count(2)
    assert not w._dot.isHidden()
    assert not w._badge.isHidden()
    assert w._badge.text() == "×2"


def test_running_count_large(widget_and_calls):
    w, _ = widget_and_calls
    w.set_running_count(10)
    assert w._badge.text() == "×10"


# ---------- set_unread_count ----------

def test_unread_count_zero_hides(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(3)
    w.set_unread_count(0)
    assert w._notif_badge.isHidden()


def test_unread_count_positive_shows(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(5)
    assert not w._notif_badge.isHidden()
    assert w._notif_badge.text() == "5"


def test_unread_count_cap_at_99(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(999)
    assert w._notif_badge.text() == "99+"


def test_unread_count_exactly_100_caps(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(100)
    assert w._notif_badge.text() == "99+"


# ---------- set_runner_count ----------

def test_runner_count_zero_hides(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_count(2)
    w.set_runner_count(0)
    assert w._runner_badge.isHidden()


def test_runner_count_positive_shows(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_count(2)
    assert not w._runner_badge.isHidden()
    assert w._runner_badge.text() == "2▶"


def test_runner_count_one(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_count(1)
    assert w._runner_badge.text() == "1▶"


# ---------- set_pinned ----------

def test_set_pinned_true_shows_icon(widget_and_calls):
    w, _ = widget_and_calls
    w.set_pinned(True)
    assert not w._pin_icon.isHidden()
    assert w._pinned is True


def test_set_pinned_false_hides_icon(widget_and_calls):
    w, _ = widget_and_calls
    w.set_pinned(True)
    w.set_pinned(False)
    assert w._pin_icon.isHidden()
    assert w._pinned is False


# ---------- set_selected ----------

def test_set_selected_true(widget_and_calls):
    w, _ = widget_and_calls
    w.set_selected(True)
    assert w._selected is True


def test_set_selected_false_after_true(widget_and_calls):
    w, _ = widget_and_calls
    w.set_selected(True)
    w.set_selected(False)
    assert w._selected is False


def test_set_selected_idempotent(widget_and_calls):
    """Chamar com o mesmo valor não deve causar repintura dupla."""
    w, _ = widget_and_calls
    w.set_selected(False)
    w.set_selected(False)  # já estava False — sem efeito extra
    assert w._selected is False


# ---------- set_label ----------

def test_set_label_updates_text(widget_and_calls):
    w, _ = widget_and_calls
    w.set_label("Novo Nome")
    assert w._label.text() == "Novo Nome"


# ---------- set_collapsed ----------

def test_set_collapsed_true_shows_chevron_right(widget_and_calls):
    w, _ = widget_and_calls
    w.set_collapsed(True)
    assert w._collapse_btn.text() == "›"


def test_set_collapsed_false_shows_chevron_down(widget_and_calls):
    w, _ = widget_and_calls
    w.set_collapsed(False)
    assert w._collapse_btn.text() == "⌄"


# ---------- callbacks ----------

def test_add_btn_triggers_callback(qapp):
    calls = []
    w = WorkspaceItemWidget(
        "X",
        on_add_claude=lambda: calls.append(1),
        on_toggle_collapse=lambda: None,
    )
    w._add_btn.click()
    assert calls == [1]
