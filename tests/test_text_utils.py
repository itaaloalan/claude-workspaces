"""Testes para claude_workspaces.ui.text_utils — função pura _strip_noise."""

import pytest

from claude_workspaces.ui.text_utils import _strip_noise


@pytest.mark.parametrize("text", [
    "",
    None,
])
def test_strip_noise_empty(text):
    assert _strip_noise(text or "") == ""


def test_strip_noise_plain_text_unchanged():
    assert _strip_noise("Escrevendo código") == "Escrevendo código"


def test_strip_noise_removes_block_bar_with_percent():
    result = _strip_noise("Context ▒▒▒░░░ 12%")
    assert "▒" not in result
    assert "12%" not in result


def test_strip_noise_removes_solid_bar_with_percent():
    result = _strip_noise("Context █████ 87%")
    assert "█" not in result
    assert "87%" not in result


def test_strip_noise_removes_context_word_percent():
    result = _strip_noise("Context 45%")
    assert result == ""


def test_strip_noise_removes_multiblock_visual_bar():
    # Barra visual sem percentual (OpenCode pattern)
    result = _strip_noise("█████████")
    assert result == ""


def test_strip_noise_keeps_useful_text_after_bar():
    result = _strip_noise("Escrevendo testes · Context ▒▒░░ 30%")
    assert "Escrevendo testes" in result
    assert "▒" not in result


def test_strip_noise_cleans_dangling_separator():
    # Separador '·' pendurado deve ser limpo
    result = _strip_noise("Ação útil · ·")
    assert result == "Ação útil"


def test_strip_noise_trims_leading_trailing_dot():
    result = _strip_noise("· Algo ·")
    assert result == "Algo"


def test_strip_noise_removes_context_case_insensitive():
    result = _strip_noise("CONTEXT ████ 50%")
    assert "CONTEXT" not in result
    assert "50%" not in result


def test_strip_noise_preserves_branch_model_line():
    # Linhas de branch/modelo não devem ser removidas
    line = "opus-4 · main · 12K"
    assert _strip_noise(line) == "opus-4 · main · 12K"


def test_strip_noise_multiple_blocks():
    result = _strip_noise("Context ▒▒ 10% · Context ███ 90%")
    assert "▒" not in result
    assert "█" not in result


def test_strip_noise_bar_without_scheme_opaque():
    # Barra multi-bloco sem espaço entre blocos (OpenCode variant)
    result = _strip_noise("████████████")
    assert result == ""


def test_shorten_model_imports_correctly():
    from claude_workspaces.ui.terminal_child_widget import _shorten_model
    assert _shorten_model("claude-opus-4-7") == "opus-4-7"
    assert _shorten_model("gpt-4") == "gpt-4"


def test_fmt_elapsed_seconds():
    from claude_workspaces.ui.terminal_child_widget import _fmt_elapsed
    assert _fmt_elapsed(45) == "45s"
    assert _fmt_elapsed(90) == "1m 30s"
    assert _fmt_elapsed(3660) == "1h 01m"
