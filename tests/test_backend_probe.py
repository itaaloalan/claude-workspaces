"""Testes de backend_probe.py — parse de versão e checagem de compatibilidade."""

from claude_workspaces.backend_probe import (
    TESTED_CLAUDE_RANGE,
    _parse_semver,
    check_compatibility,
    probe_claude_version,
    run_probe,
)

# ---------- _parse_semver ----------

def test_parse_semver_plain():
    assert _parse_semver("1.2.3") == (1, 2, 3)


def test_parse_semver_embedded_in_text():
    assert _parse_semver("claude 2.1.5 (build abc)") == (2, 1, 5)


def test_parse_semver_first_match_wins():
    assert _parse_semver("v9.9.9 then 1.0.0") == (9, 9, 9)


def test_parse_semver_none_when_absent():
    assert _parse_semver("sem versão aqui") is None
    assert _parse_semver("") is None


# ---------- check_compatibility ----------

def test_check_compat_none_version_is_false():
    assert check_compatibility(None, TESTED_CLAUDE_RANGE) is False


def test_check_compat_no_range_is_true():
    assert check_compatibility((1, 0, 0), None) is True


def test_check_compat_in_range():
    rng = ((2, 1, 0), (2, 1, 999))
    assert check_compatibility((2, 1, 5), rng) is True


def test_check_compat_at_boundaries():
    rng = ((2, 1, 0), (2, 1, 999))
    assert check_compatibility((2, 1, 0), rng) is True
    assert check_compatibility((2, 1, 999), rng) is True


def test_check_compat_below_range():
    rng = ((2, 1, 0), (2, 1, 999))
    assert check_compatibility((2, 0, 9), rng) is False


def test_check_compat_above_range():
    rng = ((2, 1, 0), (2, 1, 999))
    assert check_compatibility((3, 0, 0), rng) is False


# ---------- probe_* (caminho sem binário) ----------

def test_probe_claude_missing_binary_returns_none():
    # Comando improvável de existir no PATH → None (shutil.which falha)
    assert probe_claude_version("claude-binario-que-nao-existe-xyz") is None


def test_run_probe_does_not_raise():
    # Smoke: não deve lançar mesmo sem o binário
    run_probe("opencode")
    run_probe("claude")
