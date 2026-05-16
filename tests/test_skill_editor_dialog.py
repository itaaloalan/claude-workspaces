"""Testes do SkillEditorDialog — foca no round-trip de save."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from claude_workspaces.skills_discovery import KIND_AGENT, KIND_SKILL, ClaudeItem
from claude_workspaces.ui.skill_editor_dialog import SkillEditorDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _silence_qmessagebox(monkeypatch):
    """QMessageBox.information/critical bloqueia mesmo offscreen."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: 0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: 0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: 0)


def _make_skill(tmp_path: Path, name: str, body: str = "body inicial " * 10) -> ClaudeItem:
    d = tmp_path / name
    d.mkdir()
    path = d / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: desc valida pro lint nao reclamar tanto\n---\n\n{body}",
        encoding="utf-8",
    )
    return ClaudeItem(
        name=name, description="desc", source="user", kind=KIND_SKILL, path=path,
    )


def test_load_populates_fields(tmp_path, qapp):
    item = _make_skill(tmp_path, "demo")
    dlg = SkillEditorDialog(item)
    assert dlg._name_edit.text() == "demo"
    assert "desc valida" in dlg._desc_edit.toPlainText()
    assert "body inicial" in dlg._body_edit.toPlainText()


def test_save_writes_back(tmp_path, qapp):
    item = _make_skill(tmp_path, "demo")
    dlg = SkillEditorDialog(item)
    dlg._body_edit.setPlainText("novo conteúdo bem grande pra passar do lint mínimo " * 4)
    dlg._desc_edit.setPlainText("descrição atualizada pra ter tamanho ok agora")
    dlg._save()
    saved = item.path.read_text(encoding="utf-8")
    assert "novo conteúdo" in saved
    assert "descrição atualizada" in saved
    # Backup criado
    backup = item.path.with_suffix(item.path.suffix + ".bak")
    assert backup.exists()


def test_agent_shows_tools_field(tmp_path, qapp):
    path = tmp_path / "agent-x.md"
    path.write_text(
        "---\nname: agent-x\ndescription: desc valida pro lint nao reclamar tanto\ntools: Read, Grep\n---\n\n" + "body " * 20,
        encoding="utf-8",
    )
    item = ClaudeItem(
        name="agent-x", description="", source="user", kind=KIND_AGENT, path=path,
    )
    dlg = SkillEditorDialog(item)
    assert dlg._tools_edit is not None
    assert dlg._tools_edit.text() == "Read, Grep"


def test_skill_hides_tools_field(tmp_path, qapp):
    item = _make_skill(tmp_path, "demo")
    dlg = SkillEditorDialog(item)
    assert dlg._tools_edit is None


def test_save_disabled_with_lint_error(tmp_path, qapp):
    item = _make_skill(tmp_path, "demo")
    dlg = SkillEditorDialog(item)
    dlg._name_edit.setText("")  # E001 sem name → erro
    dlg._relint()
    assert not dlg._save_btn.isEnabled()


def test_save_enabled_when_clean(tmp_path, qapp):
    item = _make_skill(tmp_path, "demo")
    dlg = SkillEditorDialog(item)
    dlg._body_edit.setPlainText("body " * 30)
    dlg._desc_edit.setPlainText("descrição com tamanho razoável pra passar")
    dlg._relint()
    assert dlg._save_btn.isEnabled()


def test_extras_preserve_unknown_keys(tmp_path, qapp):
    path = tmp_path / "demo" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(
        "---\nname: demo\ndescription: desc valida pro lint nao reclamar tanto\nmodel: opus\ncustom: x\n---\n\nbody " + "x " * 30,
        encoding="utf-8",
    )
    item = ClaudeItem(
        name="demo", description="", source="user", kind=KIND_SKILL, path=path,
    )
    dlg = SkillEditorDialog(item)
    extras_text = dlg._extra_fm.toPlainText()
    assert "model: opus" in extras_text
    assert "custom: x" in extras_text
    dlg._save()
    saved = path.read_text(encoding="utf-8")
    assert "model: opus" in saved
    assert "custom: x" in saved
