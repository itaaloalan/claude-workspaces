"""Testes dos helpers puros de claude_activity.py (complementa test_claude_activity)."""

from claude_workspaces.claude_activity import (
    _has_working_marker,
    _is_idle_marker,
    _is_meaningful,
    _is_prompt_ready_marker,
    _last_index,
    _looks_like_prompt,
    _normalize,
)

# ---------- _is_meaningful ----------

def test_is_meaningful_true_with_alnum():
    assert _is_meaningful("Editing foo.py") is True


def test_is_meaningful_false_box_drawing():
    assert _is_meaningful("───────") is False
    assert _is_meaningful("   ") is False
    assert _is_meaningful("╰─╯") is False


# ---------- _normalize ----------

def test_normalize_strips_non_alnum_and_lowercases():
    assert _normalize("Auto-Mode ON!") == "automodeon"


def test_normalize_empty_when_only_symbols():
    assert _normalize("─·─ ") == ""


# ---------- _is_idle_marker ----------

def test_is_idle_marker_empty_line_false():
    assert _is_idle_marker("") is False
    assert _is_idle_marker("────") is False


# ---------- _last_index ----------

def test_last_index_finds_last_match():
    lines = ["a", "x", "b", "x", "c"]
    assert _last_index(lines, lambda ln: ln == "x") == 3


def test_last_index_no_match_is_minus_one():
    assert _last_index(["a", "b"], lambda ln: ln == "z") == -1


# ---------- _has_working_marker ----------

def test_has_working_marker_true():
    lines = ["blah", "* Stewing… (5s · 1.3k tokens · esc to interrupt)"]
    assert _has_working_marker(lines) is True


def test_has_working_marker_false_when_old():
    # Marker fora da janela das últimas 6 linhas não conta
    lines = ["* Working… 10 tokens"] + ["linha"] * 6
    assert _has_working_marker(lines) is False


def test_has_working_marker_false_without_marker():
    assert _has_working_marker(["Editing foo", "Reading bar"]) is False


# ---------- _looks_like_prompt ----------

def test_looks_like_prompt_tails():
    assert _looks_like_prompt(">") is True
    assert _looks_like_prompt("$") is True
    assert _looks_like_prompt("#") is True


def test_looks_like_prompt_dollar_suffix():
    assert _looks_like_prompt("user@host:~ $") is True


def test_looks_like_prompt_false():
    assert _looks_like_prompt("Editing foo.py") is False


# ---------- _is_prompt_ready_marker ----------

def test_is_prompt_ready_marker_true():
    assert _is_prompt_ready_marker("auto mode on (shift+tab to cycle)") is True
    assert _is_prompt_ready_marker("plan mode on") is True
    assert _is_prompt_ready_marker("bypass permissions") is True


def test_is_prompt_ready_marker_empty_false():
    assert _is_prompt_ready_marker("") is False
    assert _is_prompt_ready_marker("────") is False


def test_is_prompt_ready_marker_unrelated_false():
    assert _is_prompt_ready_marker("Editing src/foo.py") is False
