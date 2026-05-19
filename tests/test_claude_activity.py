from claude_workspaces.claude_activity import (
    _is_idle_marker,
    has_idle_marker,
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


def test_working_marker_persists_during_output_gap():
    """Pausa longa no streaming (extended thinking, tool run lenta,
    latência de rede) não deve flipar pra idle se o marker '* Word…
    tokens' continua visível e nenhum idle marker apareceu depois.

    Regressão: antes, gap > 2.5s flipava is_working pra False mesmo com
    o marker presente, disparando notificação '✅ Pronto' espúria que
    sumia em seguida quando o próximo chunk reativava working."""
    buf = b"Reading large file...\n* Stewing... (12s, 2.4k tokens, esc to interrupt)\n"
    a = parse_status(buf, last_output_age=5.0)
    assert a.is_working is True


def test_working_marker_persists_with_very_long_gap():
    """Mesmo com gap absurdo (30s), se o marker ainda está lá e nenhum
    idle apareceu, é working. Claude pode estar bloqueado num tool run
    lento mas continua ativo."""
    buf = b"Running pytest...\n* Cooking... (45s, 5k tokens, esc to interrupt)\n"
    a = parse_status(buf, last_output_age=30.0)
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


# ---------- has_idle_marker ----------


def test_has_idle_marker_vazio():
    assert has_idle_marker(b"") is False


def test_has_idle_marker_detecta_auto_mode():
    buf = (
        b"Welcome to Claude Code\n"
        b"Tips for getting started\n"
        b"\n"
        b"auto mode on (shift+tab to cycle)\n"
    )
    assert has_idle_marker(buf) is True


def test_has_idle_marker_detecta_shortcuts():
    buf = b"some output\n? for shortcuts\n"
    assert has_idle_marker(buf) is True


def test_has_idle_marker_falso_quando_working():
    buf = b"auto mode on\n* Stewing... (5s, 100 tokens, esc to interrupt)\n"
    # Working marker depois do idle marker → não está pronto
    assert has_idle_marker(buf) is False


def test_has_idle_marker_falso_sem_marker():
    buf = b"$ echo hello\nhello\n"
    assert has_idle_marker(buf) is False


def test_has_idle_marker_falso_quando_idle_muito_antigo():
    """Idle marker muito longe do fim do buffer não conta — Claude
    pode ter trabalhado de novo desde então."""
    buf = b"auto mode on\n" + b"linha\n" * 10
    assert has_idle_marker(buf) is False


# ---------- needs_decision (permission prompt) ----------


def test_needs_decision_false_quando_idle_normal():
    """Claude no prompt principal sem pedir nada — não é 'aguardando'."""
    buf = (
        b"Resposta finalizada.\n"
        b"auto-mode on (shift+tab to cycle)\n"
    )
    a = parse_status(buf, last_output_age=5)
    assert a.is_working is False
    assert a.needs_decision is False


def test_needs_decision_true_em_permission_prompt():
    """'Do you want to...' + setas numeradas → awaiting."""
    buf = (
        b"Bash command\n"
        b"  rm -rf /tmp/foo\n"
        b"\n"
        b"Do you want to proceed?\n"
        b"\xe2\x9d\xaf 1. Yes\n"
        b"  2. Yes, and don't ask again this session\n"
        b"  3. No, and tell Claude what to do differently\n"
    )
    a = parse_status(buf, last_output_age=5)
    assert a.is_working is False
    assert a.needs_decision is True


def test_needs_decision_true_com_make_edit():
    """Variante: 'Do you want to make this edit?'"""
    buf = (
        b"Edit src/Foo.java\n"
        b"Do you want to make this edit to Foo.java?\n"
        b"\xe2\x9d\xaf 1. Yes\n"
        b"  2. No\n"
    )
    a = parse_status(buf, last_output_age=5)
    assert a.needs_decision is True


def test_needs_decision_false_quando_working():
    """Mesmo com 'Do you want to' velho no buffer, se Claude está
    trabalhando agora não é 'aguardando' — working tem prioridade."""
    buf = (
        b"Do you want to proceed?\n"
        b"\xe2\x9d\xaf 1. Yes\n"
        b"User responded.\n"
        b"* Stewing... (3s, 800 tokens, esc to interrupt)\n"
    )
    a = parse_status(buf, last_output_age=0.3)
    assert a.is_working is True
    assert a.needs_decision is False


def test_needs_decision_false_sem_setas_de_escolha():
    """'Do you want' em texto livre, sem setas numeradas, não conta
    como permission prompt (evita falso positivo em conversa)."""
    buf = b"User asked: do you want me to run the tests?\nClaude: sure.\n"
    a = parse_status(buf, last_output_age=5)
    assert a.needs_decision is False


def test_needs_decision_true_em_picker_interativo():
    """Picker do Claude (skill picker, plan mode, choice customizado)
    fecha com footer 'Enter to select · ↑/↓ to navigate · Esc to cancel'.
    Esse footer sozinho já é prova de awaiting decision."""
    buf = (
        "Direção\n"
        "Achei 4 direções viáveis pra hoje. Qual te chama mais?\n"
        "> 1. Faxina de UX rápida\n"
        "  2. Cobertura de testes\n"
        "  3. Distribuição Linux\n"
        "Enter to select · ↑/↓ to navigate · Esc to cancel\n"
    ).encode()
    a = parse_status(buf, last_output_age=5)
    assert a.is_working is False
    assert a.needs_decision is True


def test_needs_decision_true_em_picker_sem_espacos():
    """Regressão: o Claude TUI emite o picker usando cursor positioning
    absoluto, e strip_ansi remove os escapes sem reinserir espaços. O
    footer chega como 'Entertoselect·↑/↓tonavigate·Esctocancel'. A
    detecção tem que normalizar antes de comparar pra não perder esse
    caso — sem o fix, sessões com picker aberto apareciam como Ocioso."""
    buf = (
        "Qual?\n"
        "❯ 1.OpçãoA\n"
        "2.OpçãoB\n"
        "Entertoselect·↑/↓tonavigate·Esctocancel\n"
    ).encode()
    a = parse_status(buf, last_output_age=5)
    assert a.is_working is False
    assert a.needs_decision is True


def test_needs_decision_true_em_permission_prompt_sem_espacos():
    """Mesma regressão pro permission prompt ('Doyouwant...' + ❯ N.)."""
    buf = (
        "Doyouwantmetorunthetests?\n"
        "❯ 1.Yes\n"
        "2.No\n"
    ).encode()
    a = parse_status(buf, last_output_age=5)
    assert a.needs_decision is True


def test_picker_footer_nao_vira_status_display():
    """O footer 'Enter to select…' não deve virar o display da última
    ação — preferimos a linha real (título/pergunta do picker)."""
    buf = (
        "Direção\n"
        "Qual te chama mais?\n"
        "> 1. Faxina de UX rápida\n"
        "Enter to select · ↑/↓ to navigate · Esc to cancel\n"
    ).encode()
    a = parse_status(buf, last_output_age=5)
    assert "Enter to select" not in a.status
    assert a.status
