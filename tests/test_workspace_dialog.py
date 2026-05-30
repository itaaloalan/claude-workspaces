"""Testes do WorkspaceDialog — criação e edição de workspaces."""

import pytest

from claude_workspaces.models import Workspace
from claude_workspaces.ui.workspace_dialog import WorkspaceDialog


@pytest.fixture
def new_dialog(qapp):
    """Dialog aberto no modo criação (sem workspace existente)."""
    return WorkspaceDialog()


@pytest.fixture
def edit_dialog(qapp):
    """Dialog aberto no modo edição com um workspace completo."""
    ws = Workspace(
        name="Projeto Existente",
        folders=["/home/user/proj", "/home/user/extra"],
        description="Descrição do projeto",
        branch_prefix="feat",
        default_isolate_worktree=True,
        default_create_new_branch=False,
    )
    return WorkspaceDialog(workspace=ws), ws


# ---------- modo criação ----------

def test_new_dialog_title(new_dialog):
    assert "Novo" in new_dialog.windowTitle()


def test_new_dialog_name_empty(new_dialog):
    assert new_dialog.name_edit.text() == ""


def test_new_dialog_desc_empty(new_dialog):
    assert new_dialog.desc_edit.toPlainText() == ""


def test_new_dialog_folders_empty(new_dialog):
    assert new_dialog.folders_list.count() == 0


def test_new_dialog_has_template_combo(new_dialog):
    # Modo criação deve mostrar template combo
    assert new_dialog._template_combo is not None


def test_new_workspace_from_dialog(new_dialog):
    new_dialog.name_edit.setText("Meu Projeto")
    ws = new_dialog.workspace()
    assert ws.name == "Meu Projeto"
    assert ws.id != ""  # deve gerar um id


def test_new_workspace_empty_name(new_dialog):
    ws = new_dialog.workspace()
    assert ws.name == ""


def test_new_workspace_branch_prefix(new_dialog):
    new_dialog.branch_prefix_edit.setText("feat")
    ws = new_dialog.workspace()
    assert ws.branch_prefix == "feat"


def test_new_workspace_isolate_sim(new_dialog):
    new_dialog.isolate_combo.setCurrentIndex(1)  # "Sim"
    ws = new_dialog.workspace()
    assert ws.default_isolate_worktree is True


def test_new_workspace_isolate_nao(new_dialog):
    new_dialog.isolate_combo.setCurrentIndex(2)  # "Não"
    ws = new_dialog.workspace()
    assert ws.default_isolate_worktree is False


def test_new_workspace_isolate_global(new_dialog):
    new_dialog.isolate_combo.setCurrentIndex(0)  # "Usar global"
    ws = new_dialog.workspace()
    assert ws.default_isolate_worktree is None


def test_new_workspace_create_branch_sim(new_dialog):
    new_dialog.create_branch_combo.setCurrentIndex(1)
    ws = new_dialog.workspace()
    assert ws.default_create_new_branch is True


def test_new_workspace_create_branch_nao(new_dialog):
    new_dialog.create_branch_combo.setCurrentIndex(2)
    ws = new_dialog.workspace()
    assert ws.default_create_new_branch is False


# ---------- modo edição ----------

def test_edit_dialog_title(edit_dialog):
    dlg, _ = edit_dialog
    assert "Editar" in dlg.windowTitle()


def test_edit_dialog_name_pre_filled(edit_dialog):
    dlg, ws = edit_dialog
    assert dlg.name_edit.text() == ws.name


def test_edit_dialog_desc_pre_filled(edit_dialog):
    dlg, ws = edit_dialog
    assert dlg.desc_edit.toPlainText() == ws.description


def test_edit_dialog_folders_pre_filled(edit_dialog):
    dlg, ws = edit_dialog
    assert dlg.folders_list.count() == len(ws.folders)
    items = [dlg.folders_list.item(i).text() for i in range(dlg.folders_list.count())]
    assert items == ws.folders


def test_edit_dialog_no_template_combo(edit_dialog):
    dlg, _ = edit_dialog
    assert dlg._template_combo is None


def test_edit_dialog_isolate_pre_selected(edit_dialog):
    dlg, ws = edit_dialog
    # default_isolate_worktree=True → índice 1 ("Sim")
    assert dlg.isolate_combo.currentIndex() == 1


def test_edit_dialog_create_branch_pre_selected(edit_dialog):
    dlg, ws = edit_dialog
    # default_create_new_branch=False → índice 2 ("Não")
    assert dlg.create_branch_combo.currentIndex() == 2


def test_edit_workspace_preserves_id(edit_dialog):
    dlg, ws = edit_dialog
    result = dlg.workspace()
    assert result.id == ws.id


def test_edit_workspace_preserves_runners(edit_dialog):
    dlg, ws = edit_dialog
    result = dlg.workspace()
    assert result.runners == ws.runners


def test_edit_workspace_preserves_pinned(edit_dialog):
    dlg, ws = edit_dialog
    result = dlg.workspace()
    assert result.pinned == ws.pinned


def test_edit_workspace_new_name_returned(edit_dialog):
    dlg, _ = edit_dialog
    dlg.name_edit.setText("Nome Novo")
    result = dlg.workspace()
    assert result.name == "Nome Novo"


# ---------- move_selected ----------

def test_move_selected_up(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b", "/c"])
    new_dialog.folders_list.setCurrentRow(1)
    new_dialog.move_selected(-1)
    assert new_dialog.folders_list.item(0).text() == "/b"
    assert new_dialog.folders_list.item(1).text() == "/a"


def test_move_selected_down(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b", "/c"])
    new_dialog.folders_list.setCurrentRow(0)
    new_dialog.move_selected(1)
    assert new_dialog.folders_list.item(0).text() == "/b"
    assert new_dialog.folders_list.item(1).text() == "/a"


def test_move_selected_no_op_at_top(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b"])
    new_dialog.folders_list.setCurrentRow(0)
    new_dialog.move_selected(-1)
    assert new_dialog.folders_list.item(0).text() == "/a"


def test_move_selected_no_op_at_bottom(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b"])
    new_dialog.folders_list.setCurrentRow(1)
    new_dialog.move_selected(1)
    assert new_dialog.folders_list.item(1).text() == "/b"


def test_move_selected_no_op_no_selection(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b"])
    new_dialog.folders_list.clearSelection()
    new_dialog.move_selected(-1)  # deve ignorar silenciosamente


# ---------- remove_folder ----------

def test_remove_selected_folder(new_dialog):
    new_dialog.folders_list.addItems(["/a", "/b"])
    new_dialog.folders_list.setCurrentRow(0)
    new_dialog.remove_folder()
    assert new_dialog.folders_list.count() == 1
    assert new_dialog.folders_list.item(0).text() == "/b"


# ---------- selected_template / init_claude_md ----------

def test_selected_template_returns_none_when_no_templates(edit_dialog):
    dlg, _ = edit_dialog
    assert dlg.selected_template() is None


def test_init_claude_md_false_by_default(new_dialog):
    assert new_dialog.init_claude_md() is False
