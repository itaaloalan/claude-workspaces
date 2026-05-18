from claude_workspaces.claude_probe import (
    _parse_version,
    check_compatibility,
)


def test_parse_version_real_output():
    assert _parse_version("2.1.143 (Claude Code)") == (2, 1, 143)


def test_parse_version_finds_in_noisy_string():
    assert _parse_version("Claude Code version 2.10.5\nbuild abc") == (2, 10, 5)


def test_parse_version_returns_none_when_absent():
    assert _parse_version("no version here") is None


def test_check_compatibility_within_range(caplog):
    rng = ((2, 1, 0), (2, 1, 999))
    with caplog.at_level("INFO"):
        ok = check_compatibility((2, 1, 50), rng)
    assert ok is True
    assert any("detectado" in r.message for r in caplog.records)


def test_check_compatibility_older_warns(caplog):
    rng = ((2, 1, 0), (2, 1, 999))
    with caplog.at_level("WARNING"):
        ok = check_compatibility((2, 0, 1), rng)
    assert ok is False
    assert any("ANTIGO" in r.message for r in caplog.records)


def test_check_compatibility_newer_warns(caplog):
    rng = ((2, 1, 0), (2, 1, 999))
    with caplog.at_level("WARNING"):
        ok = check_compatibility((2, 2, 0), rng)
    assert ok is False
    assert any("NOVO" in r.message for r in caplog.records)


def test_check_compatibility_none_is_false():
    assert check_compatibility(None) is False
