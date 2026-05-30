"""Testes do RunnerEditDialog e a função pura _detect_script_file."""

import pytest

from claude_workspaces.models import RunnerConfig
from claude_workspaces.ui.runner_edit_dialog import RunnerEditDialog, _detect_script_file

# ---------- _detect_script_file (pura) ----------

def test_detect_npm_with_package_json(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text("{}")
    result = _detect_script_file("npm start", str(tmp_path))
    assert result == pkg


def test_detect_yarn_with_package_json(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text("{}")
    result = _detect_script_file("yarn dev", str(tmp_path))
    assert result == pkg


def test_detect_pnpm_with_package_json(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text("{}")
    result = _detect_script_file("pnpm run build", str(tmp_path))
    assert result == pkg


def test_detect_npm_no_package_json(tmp_path):
    result = _detect_script_file("npm start", str(tmp_path))
    assert result is None


def test_detect_bash_script(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("#!/bin/bash\necho ok")
    result = _detect_script_file("bash run.sh", str(tmp_path))
    assert result == script


def test_detect_python_script(tmp_path):
    script = tmp_path / "app.py"
    script.write_text("print('hi')")
    result = _detect_script_file("python app.py", str(tmp_path))
    assert result == script


def test_detect_node_script(tmp_path):
    script = tmp_path / "server.js"
    script.write_text("console.log('hi')")
    result = _detect_script_file("node server.js", str(tmp_path))
    assert result == script


def test_detect_bash_missing_file(tmp_path):
    result = _detect_script_file("bash missing.sh", str(tmp_path))
    assert result is None


def test_detect_empty_cmd():
    assert _detect_script_file("", "/tmp") is None


def test_detect_direct_path(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("")
    result = _detect_script_file(str(script), str(tmp_path))
    assert result == script


def test_detect_unknown_cmd_returns_none(tmp_path):
    result = _detect_script_file("glassfish-start", str(tmp_path))
    assert result is None


# ---------- RunnerEditDialog ----------

@pytest.fixture
def blank_dialog(qapp):
    return RunnerEditDialog(runner=None)


@pytest.fixture
def edit_dialog(qapp):
    runner = RunnerConfig(
        name="web",
        start_cmd="npm run dev",
        stop_cmd="",
        restart_cmd="npm run restart",
        cwd="/home/user/proj",
        enabled=True,
        open_browser_on_ready=True,
        browser_url="http://localhost:3000",
        ready_pattern="ready",
    )
    return RunnerEditDialog(runner=runner), runner


# --- modo criação ---

def test_blank_dialog_title(blank_dialog):
    assert "Novo" in blank_dialog.windowTitle()


def test_blank_dialog_name_empty(blank_dialog):
    assert blank_dialog._name.text() == ""


def test_blank_dialog_result_runner_default_name(blank_dialog):
    r = blank_dialog.result_runner()
    assert r.name == "runner"


# --- modo edição ---

def test_edit_dialog_title(edit_dialog):
    dlg, _ = edit_dialog
    assert "Editar" in dlg.windowTitle()


def test_edit_dialog_name_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._name.text() == runner.name


def test_edit_dialog_start_cmd_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._start.toPlainText() == runner.start_cmd


def test_edit_dialog_stop_cmd_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._stop.toPlainText() == runner.stop_cmd


def test_edit_dialog_restart_cmd_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._restart.toPlainText() == runner.restart_cmd


def test_edit_dialog_cwd_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._cwd.text() == runner.cwd


def test_edit_dialog_enabled_checked(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._enabled.isChecked() == runner.enabled


def test_edit_dialog_browser_checked(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._open_browser.isChecked() == runner.open_browser_on_ready


def test_edit_dialog_browser_url_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._browser_url.text() == runner.browser_url


def test_edit_dialog_ready_pattern_prefilled(edit_dialog):
    dlg, runner = edit_dialog
    assert dlg._ready_pattern.text() == runner.ready_pattern


# --- result_runner ---

def test_result_runner_preserves_id(edit_dialog):
    dlg, runner = edit_dialog
    result = dlg.result_runner()
    assert result.id == runner.id


def test_result_runner_updated_name(edit_dialog):
    dlg, _ = edit_dialog
    dlg._name.setText("nova-api")
    result = dlg.result_runner()
    assert result.name == "nova-api"


def test_result_runner_empty_name_defaults_to_runner(edit_dialog):
    dlg, _ = edit_dialog
    dlg._name.setText("")
    result = dlg.result_runner()
    assert result.name == "runner"


def test_result_runner_updated_start_cmd(edit_dialog):
    dlg, _ = edit_dialog
    dlg._start.setPlainText("mvn spring-boot:run")
    result = dlg.result_runner()
    assert result.start_cmd == "mvn spring-boot:run"


def test_result_runner_enabled_toggle(edit_dialog):
    dlg, _ = edit_dialog
    dlg._enabled.setChecked(False)
    result = dlg.result_runner()
    assert result.enabled is False


def test_result_runner_browser_url(edit_dialog):
    dlg, _ = edit_dialog
    dlg._browser_url.setText("http://localhost:9090")
    result = dlg.result_runner()
    assert result.browser_url == "http://localhost:9090"


def test_result_runner_new_runner_generates_id(blank_dialog):
    r = blank_dialog.result_runner()
    assert r.id != ""
