"""Testes do RunnerChildWidget e a função pura _host_port."""

import pytest

from claude_workspaces.ui.runner_child_widget import RunnerChildWidget, _host_port

# ---------- _host_port (pura) ----------

@pytest.mark.parametrize("url,expected", [
    ("http://localhost:3000", "localhost:3000"),
    ("https://myapp.example.com:8080", "myapp.example.com:8080"),
    ("http://localhost", "localhost"),
    ("localhost:4200", "localhost:4200"),
    ("", ""),
    ("invalid", "invalid"),
])
def test_host_port(url, expected):
    assert _host_port(url) == expected


def test_host_port_no_scheme_with_port():
    assert _host_port("0.0.0.0:8080") == "0.0.0.0:8080"


# ---------- RunnerChildWidget ----------

@pytest.fixture
def runner_widget(qapp):
    calls = {}
    w = RunnerChildWidget(
        "glassfish-ogpms",
        on_toggle=lambda: calls.update(toggle=True),
    )
    return w, calls


def test_name_label(runner_widget):
    w, _ = runner_widget
    assert w._name_label.text() == "glassfish-ogpms"


def test_initial_state_idle(runner_widget):
    w, _ = runner_widget
    assert w._state == "idle"


def test_initial_addr_hidden(runner_widget):
    w, _ = runner_widget
    assert w._addr_label.isHidden()


def test_set_state_running(runner_widget):
    w, _ = runner_widget
    w.set_state("running")
    assert w._state == "running"
    assert "Running" in w._status_label.text()


def test_set_state_idle_shows_idle(runner_widget):
    w, _ = runner_widget
    w.set_state("running")
    w.set_state("idle")
    assert w._state == "idle"
    assert "Idle" in w._status_label.text()


def test_set_state_error(runner_widget):
    w, _ = runner_widget
    w.set_state("error")
    assert "Failed" in w._status_label.text()


def test_set_state_exited_treated_as_idle(runner_widget):
    w, _ = runner_widget
    w.set_state("exited")
    assert "Idle" in w._status_label.text()


def test_set_state_unknown_falls_back_to_idle(runner_widget):
    w, _ = runner_widget
    w.set_state("unknown_state")
    assert w._state == "idle"


def test_running_toggle_btn_shows_stop(runner_widget):
    w, _ = runner_widget
    w.set_state("running")
    assert w._toggle_btn.text() == "■"
    assert "Parar" in w._toggle_btn.toolTip()


def test_idle_toggle_btn_shows_start(runner_widget):
    w, _ = runner_widget
    assert w._toggle_btn.text() == "▶"
    assert "Iniciar" in w._toggle_btn.toolTip()


def test_set_url_shows_addr(runner_widget):
    w, _ = runner_widget
    w.set_url("http://localhost:3000")
    assert not w._addr_label.isHidden()
    assert w._addr_label.text() == "localhost:3000"


def test_set_url_empty_hides_addr(runner_widget):
    w, _ = runner_widget
    w.set_url("http://localhost:3000")
    w.set_url("")
    assert w._addr_label.isHidden()


def test_set_url_stores_full_url(runner_widget):
    w, _ = runner_widget
    w.set_url("http://localhost:8080")
    assert w._addr_url == "http://localhost:8080"


def test_set_url_adds_scheme_if_missing(runner_widget):
    w, _ = runner_widget
    w.set_url("localhost:9090")
    assert w._addr_url == "http://localhost:9090"


def test_set_name(runner_widget):
    w, _ = runner_widget
    w.set_name("novo-runner")
    assert w._name_label.text() == "novo-runner"


def test_preferred_height(runner_widget):
    w, _ = runner_widget
    assert w.preferred_height() == RunnerChildWidget._CARD_HEIGHT


def test_set_status_transient_startando(runner_widget):
    w, _ = runner_widget
    w.set_status("startando")
    assert "Startando..." in w._status_label.text()


def test_set_status_transient_reiniciando(runner_widget):
    w, _ = runner_widget
    w.set_status("reiniciando")
    assert "reiniciando" in w._status_label.text()


def test_set_status_non_transient_restores_state(runner_widget):
    w, _ = runner_widget
    w.set_state("running")
    w.set_status("startando")
    w.set_status("outro")
    # Deve restaurar o label de estado padrão
    assert "Running" in w._status_label.text()
