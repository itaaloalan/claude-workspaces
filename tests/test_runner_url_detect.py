"""Testes de services/runner_url_detect.py — detecção de URL/porta/PR/MR.

Módulo puro (regex), sem teste até agora. É a mesma detecção de PR/MR que
originou o bug de chip duplicado por trailing slash (0.77.2), então serve
também como blindagem de regressão.
"""

from claude_workspaces.services.runner_url_detect import (
    detect_pr_url,
    detect_url,
    pr_label_from_url,
    pr_number_from_url,
    strip_ansi,
)

# ---------- detect_url: URL crua ----------

def test_detect_url_basic_http():
    assert detect_url("Server: http://localhost:3000") == "http://localhost:3000"


def test_detect_url_https_with_path():
    out = detect_url("open https://localhost:8443/app/index")
    assert out == "https://localhost:8443/app/index"


def test_detect_url_last_wins():
    text = "warning http://localhost:1111\nready http://localhost:2222"
    assert detect_url(text) == "http://localhost:2222"


def test_detect_url_rewrites_0000_to_localhost():
    assert detect_url("Listening http://0.0.0.0:5000") == "http://localhost:5000"


def test_detect_url_strips_trailing_punctuation():
    assert detect_url("Visit http://localhost:3000.") == "http://localhost:3000"


def test_detect_url_strips_ansi_before_match():
    text = "\x1b[32mhttp://localhost:4321\x1b[0m"
    assert detect_url(text) == "http://localhost:4321"


# ---------- detect_url: fallback por porta ----------

def test_detect_url_port_listening_on():
    assert detect_url("Listening on 3000") == "http://localhost:3000/"


def test_detect_url_port_with_label():
    assert detect_url("port: 8080") == "http://localhost:8080/"


def test_detect_url_running_on_port():
    assert detect_url("running on port 4200") == "http://localhost:4200/"


def test_detect_url_port_with_host_prefix():
    assert detect_url("Listening on 127.0.0.1:9090") == "http://localhost:9090/"


# ---------- detect_url: vazio / sem match ----------

def test_detect_url_empty():
    assert detect_url("") is None
    assert detect_url(None) is None


def test_detect_url_no_match():
    assert detect_url("nada de url aqui, só texto") is None


# ---------- strip_ansi ----------

def test_strip_ansi_color_codes():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_strip_ansi_osc_title():
    assert strip_ansi("\x1b]0;window title\x07hello") == "hello"


def test_strip_ansi_plain_unchanged():
    assert strip_ansi("texto limpo") == "texto limpo"


# ---------- detect_pr_url ----------

def test_detect_pr_url_github():
    text = "PR criado: https://github.com/foo/bar/pull/42"
    assert detect_pr_url(text) == "https://github.com/foo/bar/pull/42"


def test_detect_pr_url_gitlab_merge_request():
    text = "MR: https://gitlab.com/foo/bar/-/merge_requests/7"
    assert detect_pr_url(text) == "https://gitlab.com/foo/bar/-/merge_requests/7"


def test_detect_pr_url_github_wins_over_gitlab():
    text = (
        "https://gitlab.com/x/y/-/merge_requests/1 "
        "https://github.com/a/b/pull/9"
    )
    assert detect_pr_url(text) == "https://github.com/a/b/pull/9"


def test_detect_pr_url_last_github_wins():
    text = "https://github.com/a/b/pull/1 https://github.com/a/b/pull/2"
    assert detect_pr_url(text) == "https://github.com/a/b/pull/2"


def test_detect_pr_url_strips_trailing_punctuation():
    assert detect_pr_url("veja https://github.com/a/b/pull/5.") == (
        "https://github.com/a/b/pull/5"
    )


def test_detect_pr_url_none():
    assert detect_pr_url("") is None
    assert detect_pr_url("sem pr aqui") is None


# ---------- pr_number_from_url ----------

def test_pr_number_github():
    assert pr_number_from_url("https://github.com/a/b/pull/42") == "42"


def test_pr_number_gitlab():
    assert pr_number_from_url("https://gitlab.com/a/b/-/merge_requests/7") == "7"


def test_pr_number_none():
    assert pr_number_from_url("https://github.com/a/b") is None


# ---------- pr_label_from_url ----------

def test_pr_label_github():
    assert pr_label_from_url("https://github.com/a/b/pull/42") == "PR #42"


def test_pr_label_gitlab():
    assert pr_label_from_url("https://gitlab.com/a/b/-/merge_requests/7") == "MR #7"


def test_pr_label_no_number_github():
    assert pr_label_from_url("https://github.com/a/b") == "PR"


def test_pr_label_no_number_falls_back_to_pr():
    # O prefixo MR depende de _MR_NUM_RE (exige dígito). Uma URL de
    # merge_requests SEM número cai em "PR" — caso só teórico, já que
    # detect_pr_url só casa URLs com número.
    assert pr_label_from_url("https://gitlab.com/a/b/-/merge_requests/") == "PR"


# ---- url_port / swap_url_port ------------------------------------------------


def test_url_port():
    from claude_workspaces.services.runner_url_detect import url_port

    assert url_port("http://localhost:4201/x") == 4201
    assert url_port("https://dev.local/x") == 0
    assert url_port("") == 0


def test_swap_url_port_preserva_path_e_query():
    from claude_workspaces.services.runner_url_detect import swap_url_port

    assert swap_url_port("http://localhost:4201/a/b?q=1", 4202) == (
        "http://localhost:4202/a/b?q=1"
    )
    assert swap_url_port(
        "http://localhost:8088/ogpms/faces/login/login_ogpms.xhtml", 8089
    ) == "http://localhost:8089/ogpms/faces/login/login_ogpms.xhtml"


def test_swap_url_port_sem_porta_ou_zero_intacta():
    from claude_workspaces.services.runner_url_detect import swap_url_port

    assert swap_url_port("http://localhost/x", 4202) == "http://localhost/x"
    assert swap_url_port("http://localhost:4201/x", 0) == "http://localhost:4201/x"
    assert swap_url_port("", 4202) == ""
