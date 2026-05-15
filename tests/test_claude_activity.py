from claude_workspaces.claude_activity import (
    _is_idle_marker,
    parse_status,
    strip_ansi,
)


def test_empty_buffer():
    a = parse_status(b"", last_output_age=0)
    assert a.status == ""
    assert a.is_working is False


def test_strip_ansi_csi():
    raw = "\x1b[31mvermelho\x1b[0m e \x1b[1mbold\x1b[0m"
    assert strip_ansi(raw) == "vermelho e bold"


def test_strip_ansi_osc():
    raw = "\x1b]0;title\x07texto"
    assert strip_ansi(raw) == "texto"


def test_strip_ansi_control_chars():
    raw = "olá\x00\x01mundo"
    assert strip_ansi(raw) == "olámundo"


def test_strip_ansi_preserves_newline_tab():
    raw = "a\nb\tc"
    assert strip_ansi(raw) == "a\nb\tc"


def test_idle_marker_detection():
    assert _is_idle_marker("auto mode on (shift+tab to cycle)")
    assert _is_idle_marker("AUTO MODE ON")
    assert _is_idle_marker("automodeon")  # ANSI-stripped sem espaços
    assert _is_idle_marker("press shift+tab to cycle")
    assert _is_idle_marker("esc to interrupt")
    assert not _is_idle_marker("Editing src/Foo.java")
    assert not _is_idle_marker("Stewing... (5s)")


def test_skips_footer_uses_previous_line():
    """Quando a última linha é o footer do Claude, mostra a anterior
    (o que ele realmente fez)."""
    buf = (
        b"Reading file Foo.java\n"
        b"Editing src/Bar.java\n"
        b"auto mode on (shift+tab to cycle) esc to interrupt\n"
    )
    a = parse_status(buf, last_output_age=10)
    assert a.status == "Editing src/Bar.java"
    assert a.is_working is False  # output velho


def test_recent_output_marks_working():
    buf = b"* Stewing... (5s)\nReading file foo.java\n"
    a = parse_status(buf, last_output_age=0.5)
    assert a.is_working is True


def test_strips_star_prefix():
    buf = b"* Cultivating thoughts...\n"
    a = parse_status(buf, last_output_age=0.5)
    assert a.status == "Cultivating thoughts..."


def test_truncates_long_lines():
    long = "x" * 200
    buf = (long + "\n").encode()
    a = parse_status(buf, last_output_age=0.5)
    assert len(a.status) <= 90
    assert a.status.endswith("…")


def test_only_box_drawing_filtered():
    """Linhas só com box-drawing devem ser ignoradas."""
    buf = "──────────\n│         │\nReal text\n".encode()
    a = parse_status(buf, last_output_age=0.5)
    assert a.status == "Real text"
