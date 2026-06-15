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


# ---------- marcador de runner em execução ----------

def test_runner_badge_hidden_by_default(widget_and_calls):
    w, _ = widget_and_calls
    assert w._runner_badge.isHidden()
    assert w._runner_running == 0


def test_runner_badge_shows_play_for_single(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_running(1)
    assert not w._runner_badge.isHidden()
    assert w._runner_badge.text() == "▶"
    assert w._runner_running == 1


def test_runner_badge_shows_count_for_multiple(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_running(3)
    assert not w._runner_badge.isHidden()
    assert w._runner_badge.text() == "▶ 3"
    assert w.status_info()["runner_running"] == 3


def test_runner_badge_hides_when_back_to_zero(widget_and_calls):
    w, _ = widget_and_calls
    w.set_runner_running(2)
    w.set_runner_running(0)
    assert w._runner_badge.isHidden()
    assert w._runner_running == 0


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


# ---------- update_git_info: ahead/behind + arquivos + worktree ----------

def _gitfile(status, path):
    from claude_workspaces.git_status import GitFile
    return GitFile(status=status, path=path)


def test_update_git_info_ahead_behind_no_chip(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 0, ahead=2, behind=1)
    text = w._git_label.text()
    assert "↑2" in text
    assert "↓1" in text


def test_update_git_info_ahead_behind_zero_omitidos(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 0)
    text = w._git_label.text()
    assert "↑" not in text
    assert "↓" not in text


def test_update_git_info_modified_e_link(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 3)
    assert "●3" in w._git_label.text()
    assert "href='git'" in w._git_label.text()


def test_update_git_info_tooltip_lista_arquivos(widget_and_calls):
    w, _ = widget_and_calls
    files = [_gitfile(" M", "src/app.py"), _gitfile("??", "novo.txt")]
    w.update_git_info("main", 2, files=files)
    tip = w._git_label.toolTip()
    assert "modificado — src/app.py" in tip
    assert "novo — novo.txt" in tip


def test_update_git_info_tooltip_trunca_em_10(widget_and_calls):
    w, _ = widget_and_calls
    files = [_gitfile(" M", f"f{i}.py") for i in range(14)]
    w.update_git_info("main", 14, files=files)
    tip = w._git_label.toolTip()
    assert "… e mais 4 arquivo(s)" in tip


def test_update_git_info_worktree_badge_wt(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("feat/x", 0, is_worktree=True, worktree_dir="/tmp/wt")
    assert "wt" in w._git_label.text()
    assert "🌿" in w._git_label.text()
    assert "/tmp/wt" in w._git_label.toolTip()


def test_update_git_info_compat_3_args(widget_and_calls):
    # Chamada antiga com 3 args posicionais continua funcionando.
    w, _ = widget_and_calls
    w.update_git_info("main", 2, True)
    assert w._git_label.isVisible() or w._git_label.text() != ""


def test_open_git_requested_emitido_no_link(widget_and_calls):
    w, _ = widget_and_calls
    got = []
    w.open_git_requested.connect(lambda: got.append(True))
    w._git_label.linkActivated.emit("git")
    assert got == [True]


def test_status_info_expoe_ahead_behind(widget_and_calls):
    w, _ = widget_and_calls
    w.update_git_info("main", 1, ahead=3, behind=2)
    info = w.status_info()
    assert info["ahead"] == 3
    assert info["behind"] == 2


# ---------- set_pr_info: estado/cor + update in-place ----------

def test_set_pr_info_open_verde(widget_and_calls):
    from claude_workspaces.ui import theme
    w, _ = widget_and_calls
    w.set_pr_info("https://github.com/o/r/pull/7", "OPEN", 7)
    chip = w._pr_chips["https://github.com/o/r/pull/7"]
    assert theme.PR_OPEN in chip.text()
    assert "Aberto" in chip.toolTip()


def test_set_pr_info_merged_atualiza_in_place(widget_and_calls):
    from claude_workspaces.ui import theme
    w, _ = widget_and_calls
    url = "https://github.com/o/r/pull/7"
    w.set_pr_info(url, "OPEN", 7)
    w.set_pr_info(url, "MERGED", 7)
    assert len(w._pr_chips) == 1
    chip = w._pr_chips[url]
    assert theme.PR_MERGED in chip.text()
    assert "✓" in chip.text()
    assert "Merged" in chip.toolTip()


def test_set_pr_info_draft_cinza(widget_and_calls):
    from claude_workspaces.ui import theme
    w, _ = widget_and_calls
    w.set_pr_info("https://github.com/o/r/pull/8", "OPEN", 8, draft=True)
    chip = w._pr_chips["https://github.com/o/r/pull/8"]
    assert theme.PR_DRAFT in chip.text()
    assert "draft" in chip.text()


def test_set_pr_url_compat_rosa(widget_and_calls):
    from claude_workspaces.ui import theme
    w, _ = widget_and_calls
    w.set_pr_url("https://github.com/o/r/pull/9")
    chip = w._pr_chips["https://github.com/o/r/pull/9"]
    assert theme.PR_PINK in chip.text()
    assert "https://github.com/o/r/pull/9" in w._pr_urls


# ---------- retenção da última ação ----------

def test_last_action_retida_ao_aguardar(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "Editando foo.py")
    w.update_state(STATE_AWAITING, "")
    assert "Editando foo.py" in w._state_label.text()


def test_last_action_retida_ao_ficar_ocioso(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "Rodando testes")
    w.update_state(STATE_IDLE, "")
    assert "Rodando testes" in w._state_label.text()


def test_last_action_limpa_em_done(widget_and_calls):
    w, _ = widget_and_calls
    w.update_state(STATE_WORKING, "Editando foo.py")
    w.update_state(STATE_DONE, "")
    assert "Editando foo.py" not in w._state_label.text()


def test_state_tooltip_tem_acao_completa(widget_and_calls):
    w, _ = widget_and_calls
    long_action = "Uma ação muito longa que certamente passa dos cinquenta e cinco caracteres do label"
    w.update_state(STATE_WORKING, long_action)
    assert long_action in w._state_label.toolTip()
    assert "Estado: Trabalhando" in w._state_label.toolTip()
