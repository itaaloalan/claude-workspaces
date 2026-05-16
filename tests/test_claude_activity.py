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
    assert _is_idle_marker("auto-mode on")  # variante com hífen
    assert _is_idle_marker("press shift+tab to cycle")
    assert _is_idle_marker("esc to interrupt")
    assert _is_idle_marker("? for shortcuts")
    assert _is_idle_marker("⏵⏵ accept edits on (shift+tab to cycle)")
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


def test_recent_output_marks_working_with_marker():
    """Detecção positiva: precisa do indicador completo do Claude."""
    buf = b"* Stewing... (5s, 1.2k tokens, esc to interrupt)\nReading file foo.java\n"
    a = parse_status(buf, last_output_age=0.5)
    assert a.is_working is True


def test_idle_marker_overrides_recent_output():
    """Cursor piscando no prompt mantém output recente, mas sem o
    indicador de working o estado tem que cair pra idle."""
    buf = (
        b"Resposta finalizada.\n"
        b"auto-mode on (shift+tab to cycle) esc to interrupt\n"
    )
    a = parse_status(buf, last_output_age=0.3)
    assert a.is_working is False


def test_idle_footer_with_hyphen_variant():
    """Variante com hífen ('auto-mode') também tem que ser idle."""
    buf = b"Resposta.\nauto-mode on - shift+tab to cycle\n"
    a = parse_status(buf, last_output_age=0.3)
    assert a.is_working is False


def test_working_marker_then_idle_marker_at_tail():
    """Buffer com working antigo + idle marker recente = idle."""
    buf = (
        b"* Stewing... (3s, 800 tokens, esc to interrupt)\n"
        b"Done.\n"
        b"auto mode on (shift+tab to cycle)\n"
    )
    a = parse_status(buf, last_output_age=0.5)
    # Idle marker no tail e working marker fora da janela do tail → idle
    assert a.is_working is False


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
