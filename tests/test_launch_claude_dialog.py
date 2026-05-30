"""Testes do LaunchClaudeDialog — dialog de abertura de console Claude."""

import pytest

from claude_workspaces.models import Workspace
from claude_workspaces.settings import Settings


def _make_dialog(qapp, workspace, settings=None):
    from claude_workspaces.ui.launch_claude_dialog import LaunchClaudeDialog
    s = settings or Settings()
    return LaunchClaudeDialog(workspace, s)


@pytest.fixture
def empty_workspace():
    """Workspace sem pastas — não chama get_status nem list_local_branches."""
    return Workspace(name="Vazio", folders=[])


@pytest.fixture
def single_folder_workspace(tmp_path):
    """Workspace com uma pasta mas sem git (sem .git directory)."""
    return Workspace(name="Proj", folders=[str(tmp_path)])


# ---------- workspace sem pastas ----------

def test_dialog_title(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert "Abrir Claude" in dlg.windowTitle()


def test_result_folders_empty_when_no_folders(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert dlg.result_folders() == []


def test_ok_btn_disabled_when_no_folders(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert not dlg._ok_btn.isEnabled()


def test_isolate_disabled_when_no_repo(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert not dlg.isolate_chk.isEnabled()


def test_new_branch_disabled_when_no_repo(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert not dlg.new_branch_chk.isEnabled()


def test_result_isolate_false_when_no_repo(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert dlg.result_isolate() is False


def test_initial_prompt_empty(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    assert dlg.result_initial_prompt() == ""


def test_initial_prompt_set(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    dlg.initial_prompt_edit.setPlainText("Revise o arquivo X")
    assert dlg.result_initial_prompt() == "Revise o arquivo X"


# ---------- workspace com pasta mas sem git ----------

def test_result_folders_returns_checked_folders(qapp, single_folder_workspace):
    """A pasta deve aparecer como folder checkbox marcada."""
    dlg = _make_dialog(qapp, single_folder_workspace)
    folders = dlg.result_folders()
    assert len(folders) == 1
    assert str(single_folder_workspace.folders[0]) in folders[0]


def test_ok_btn_enabled_when_has_folder(qapp, single_folder_workspace):
    dlg = _make_dialog(qapp, single_folder_workspace)
    assert dlg._ok_btn.isEnabled()


def test_uncheck_only_folder_disables_ok(qapp, single_folder_workspace):
    dlg = _make_dialog(qapp, single_folder_workspace)
    # Desmarca o único checkbox de pasta
    dlg._folder_checks[0][0].setChecked(False)
    assert not dlg._ok_btn.isEnabled()


def test_is_repo_false_for_non_git_dir(qapp, single_folder_workspace, monkeypatch):
    """tmp_path não é repo git — is_repo deve ser False."""
    # Monkeypatcha get_status pra retornar None (não repo)
    from claude_workspaces import git_status
    monkeypatch.setattr(git_status, "get_status", lambda p: None)
    dlg = _make_dialog(qapp, single_folder_workspace)
    assert dlg._is_repo is False


def test_isolate_disabled_for_non_git_dir(qapp, single_folder_workspace, monkeypatch):
    from claude_workspaces import git_status
    monkeypatch.setattr(git_status, "get_status", lambda p: None)
    dlg = _make_dialog(qapp, single_folder_workspace)
    assert not dlg.isolate_chk.isEnabled()


# ---------- settings defaults ----------

def test_settings_default_create_branch(qapp, empty_workspace):
    s = Settings()
    s.default_create_new_branch = True
    dlg = _make_dialog(qapp, empty_workspace, s)
    # new_branch_chk não está enabled (sem repo), mas o valor padrão
    # vem das settings — só verificamos sem crash
    assert dlg.new_branch_chk.isChecked() is True


def test_result_create_branch_reflects_checkbox(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    dlg.new_branch_chk.setChecked(True)
    assert dlg.result_create_branch() is True
    dlg.new_branch_chk.setChecked(False)
    assert dlg.result_create_branch() is False


def test_workspace_override_branch_prefix(qapp):
    ws = Workspace(name="X", folders=[], branch_prefix="hotfix")
    dlg = _make_dialog(qapp, ws)
    # suggest_branch_name usa o prefix — deve começar com "hotfix"
    assert dlg.branch_edit.text().startswith("hotfix")


# ---------- result_branch ----------

def test_result_branch_when_new_branch_checked(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    dlg.new_branch_chk.setChecked(True)
    dlg.branch_edit.setText("feat/minha-branch")
    assert dlg.result_branch() == "feat/minha-branch"


def test_result_branch_when_new_branch_unchecked(qapp, empty_workspace):
    dlg = _make_dialog(qapp, empty_workspace)
    dlg.new_branch_chk.setChecked(False)
    # existing_combo vazia (sem repo) → string vazia
    assert dlg.result_branch() == ""
