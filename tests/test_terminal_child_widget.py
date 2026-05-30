"""Testes do TerminalChildWidget — card de console Claude na sidebar."""

import pytest

from claude_workspaces.ui.terminal_child_widget import (
    STATE_AWAITING,
    STATE_COLOR,
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_LABEL,
    STATE_PLANNING,
    STATE_WORKING,
    TerminalChildWidget,
)


@pytest.fixture
def widget_and_calls(qapp):
    calls = {}
    w = TerminalChildWidget("claude #1")
    w.set_action_callbacks(
        on_continue=lambda: calls.update(cont=True),
        on_close=lambda: calls.update(close=True),
        on_rename=lambda: calls.update(rename=True),
    )
    return w, calls


# ---------- constantes de estado ----------

def test_all_states_have_label():
    for state in (STATE_WORKING, STATE_PLANNING, STATE_AWAITING, STATE_IDLE, STATE_DONE, STATE_ERROR):
        assert state in STATE_LABEL


def test_all_states_have_color():
    for state in (STATE_WORKING, STATE_PLANNING, STATE_AWAITING, STATE_IDLE, STATE_DONE, STATE_ERROR):
        assert state in STATE_COLOR


def test_state_labels_pt_br():
    assert STATE_LABEL[STATE_WORKING] == "Trabalhando"
    assert STATE_LABEL[STATE_IDLE] == "Ocioso"
    assert STATE_LABEL[STATE_AWAITING] == "Aguardando decisão"
    assert STATE_LABEL[STATE_DONE] == "Concluído"
    assert STATE_LABEL[STATE_ERROR] == "Erro"
    assert STATE_LABEL[STATE_PLANNING] == "Planejando"


# ---------- construção ----------

def test_title_stored(widget_and_calls):
    w, _ = widget_and_calls
    assert w._title == "claude #1"


def test_initial_state_idle(widget_and_calls):
    w, _ = widget_and_calls
    assert w._current_state == STATE_IDLE


def test_initial_not_selected(widget_and_calls):
    w, _ = widget_and_calls
    assert w._selected is False


def test_initial_notif_badge_hidden(widget_and_calls):
    w, _ = widget_and_calls
    assert w._notif_badge.isHidden()


# ---------- update_state ----------

def test_update_state_working_sets_current_state(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "rodando testes")
    assert w._current_state == STATE_WORKING


def test_update_state_working_state_label_contains_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "rodando testes")
    assert "Trabalhando" in w._state_label.text()


def test_update_state_working_last_action_in_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "rodando testes")
    assert "rodando testes" in w._state_label.text()


def test_update_state_idle_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_IDLE, "")
    assert w._state_label.text() == "Ocioso"


def test_update_state_done_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_DONE, "")
    assert "Concluído" in w._state_label.text()


def test_update_state_error_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_ERROR, "")
    assert "Erro" in w._state_label.text()


def test_update_state_awaiting_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_AWAITING, "Devo continuar?")
    assert "Aguardando decisão" in w._state_label.text()


def test_update_state_planning_label(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_PLANNING, "")
    assert "Planejando" in w._state_label.text()


def test_update_state_strips_noise_from_last_action(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "Context ████ 50%")
    # Barras devem ser removidas; label não pode conter lixo
    assert "████" not in w._state_label.text()


def test_update_state_truncates_long_action(widget_and_calls):
    w, _ = widget_and_calls
    long_action = "a" * 100
    w.update_state(STATE_WORKING, long_action)
    assert len(w._last_action) <= 55


# ---------- set_selected ----------

def test_set_selected_true(widget_and_calls):
    w, _ = widget_and_calls
    w.set_selected(True)
    assert w._selected is True


def test_set_selected_false(widget_and_calls):
    w, _ = widget_and_calls
    w.set_selected(True)
    w.set_selected(False)
    assert w._selected is False


def test_set_selected_connector_label(widget_and_calls):
    w, _ = widget_and_calls
    w.set_selected(True)
    assert w._connector_label.text() == "╰"
    w.set_selected(False)
    assert w._connector_label.text() == ""


# ---------- set_unread_count ----------

def test_unread_count_zero_hides(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(3)
    w.set_unread_count(0)
    assert w._notif_badge.isHidden()


def test_unread_count_positive_shows(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(3)
    assert not w._notif_badge.isHidden()
    assert w._notif_badge.text() == "3"


def test_unread_count_caps_at_99(widget_and_calls):
    w, _ = widget_and_calls
    w.set_unread_count(500)
    assert w._notif_badge.text() == "99+"


# ---------- set_title ----------

def test_set_title_updates_title(widget_and_calls):
    w, _ = widget_and_calls
    w.set_title("claude #2")
    assert w._title == "claude #2"


# ---------- update_git_info ----------

def test_update_git_info_shows_branch(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 0)
    assert not w._git_label.isHidden()
    assert "main" in w._git_label.text()


def test_update_git_info_empty_branch_hides(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 0)
    w.update_git_info("", 0)
    assert w._git_label.isHidden()


def test_update_git_info_modified_count(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("feat/x", 5)
    assert "5" in w._git_label.text()


# ---------- update_session_info ----------

def test_update_session_info_shows_model(widget_and_calls):
    w, _ = widget_and_calls
    w.update_session_info("claude-opus-4-7", 0, 0, 0)
    assert not w._session_label.isHidden()
    assert "opus-4-7" in w._session_label.text()


def test_update_session_info_empty_model_hides(widget_and_calls):
    w, _ = widget_and_calls
    w.update_session_info("claude-opus-4-7", 0, 0, 0)
    w.update_session_info("", 0, 0, 0)
    assert w._session_label.isHidden()


# ---------- set_pr_url ----------

def test_set_pr_url_shows_chip(widget_and_calls):
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/foo/bar/pull/42")
    assert not w._pr_chips_container.isHidden()
    assert w._pr_chips_layout.count() == 1


def test_set_pr_url_empty_ignored(widget_and_calls):
    w, _ = widget_and_calls
    w.set_pr_url("")
    assert w._pr_chips_container.isHidden()


def test_set_pr_url_dedup(widget_and_calls):
    """Mesma URL não deve adicionar chip duplicado."""
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/foo/bar/pull/1")
    w.set_pr_url("https://github.com/foo/bar/pull/1")
    assert w._pr_chips_layout.count() == 1


def test_set_pr_url_multiple_different_urls(widget_and_calls):
    """URLs diferentes acumulam chips distintos."""
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/foo/bar/pull/1")
    w.set_pr_url("https://gitlab.com/foo/bar/-/merge_requests/7")
    assert w._pr_chips_layout.count() == 2


def test_set_pr_url_trailing_slash_dedup(widget_and_calls):
    """URL com trailing slash não deve criar chip duplicado (normalização)."""
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/foo/bar/pull/1")
    w.set_pr_url("https://github.com/foo/bar/pull/1/")
    assert w._pr_chips_layout.count() == 1


# ---------- status_info snapshot ----------

def test_status_info_keys(widget_and_calls):
    w, _ = widget_and_calls
    info = w.status_info()
    for key in ("state", "state_text", "state_color", "model", "branch", "modified", "title"):
        assert key in info


def test_status_info_state_matches_current(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_DONE, "")
    assert w.status_info()["state"] == STATE_DONE


def test_status_info_exposes_all_pr_urls(widget_and_calls):
    """`pr_urls` traz todos os MR/PR (footer renderiza um link por pasta)."""
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/foo/bar/pull/1")
    w.set_pr_url("https://gitlab.com/foo/bar/-/merge_requests/7")
    info = w.status_info()
    assert info["pr_urls"] == [
        "https://github.com/foo/bar/pull/1",
        "https://gitlab.com/foo/bar/-/merge_requests/7",
    ]
    # compat: pr_url segue sendo o último
    assert info["pr_url"] == "https://gitlab.com/foo/bar/-/merge_requests/7"


# ---------- cor do robô segue o estado ----------

def test_robot_pixmap_cached_per_state(widget_and_calls):
    w, _ = widget_and_calls
    p1 = w._robot_pixmap(STATE_WORKING)
    p2 = w._robot_pixmap(STATE_WORKING)
    assert p1 is p2  # mesmo estado → mesmo pixmap cacheado
    assert w._robot_pixmap(STATE_ERROR) is not p1


def test_robot_color_follows_state_on_update(widget_and_calls):
    """update_state troca o pixmap do robô pelo da cor do estado atual."""
    w, _ = widget_and_calls
    for state in (STATE_WORKING, STATE_AWAITING, STATE_IDLE, STATE_ERROR, STATE_DONE):
        w.update_state(state, "")
        assert w._claude_icon.pixmap().cacheKey() == w._robot_pixmap(state).cacheKey()


def test_selection_does_not_change_robot_color(widget_and_calls):
    """Seleção não mexe na cor do robô — ele segue só o estado."""
    w, _ = widget_and_calls
    w.update_state(STATE_AWAITING, "")
    before = w._claude_icon.pixmap().cacheKey()
    w.set_selected(True)
    assert w._claude_icon.pixmap().cacheKey() == before


# ---------- callbacks ----------

def test_close_btn_triggers_callback(qapp):
    calls = []
    w = TerminalChildWidget("t")
    w.set_action_callbacks(
        on_continue=lambda: None,
        on_close=lambda: calls.append("close"),
    )
    w._close_btn.clicked.emit()
    assert calls == ["close"]


def test_continue_btn_triggers_callback(qapp):
    calls = []
    w = TerminalChildWidget("t")
    w.set_action_callbacks(
        on_continue=lambda: calls.append("cont"),
    )
    w._continue_btn.clicked.emit()
    assert calls == ["cont"]


# ---------- tick helpers ----------

def test_tick_idle_does_nothing_when_not_idle(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "x")
    # Should not crash; idle_since is None in working state
    w.tick_idle()


def test_tick_awaiting_toggles_blink(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_AWAITING, "Devo continuar?")
    before = w._awaiting_blink_on
    w.tick_awaiting()
    assert w._awaiting_blink_on != before


def test_tick_awaiting_resets_when_not_awaiting(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_AWAITING, "?")
    w.tick_awaiting()  # ativa pisca
    w.update_state(STATE_IDLE, "")
    w.tick_awaiting()  # fora do estado → reseta
    assert w._awaiting_blink_on is False
