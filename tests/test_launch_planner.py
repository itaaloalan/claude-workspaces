from pathlib import Path

from claude_workspaces.services.launch_planner import (
    build_claude_argv,
    plan_from_dialog,
)


def test_no_folders_is_error():
    plan = plan_from_dialog([], False, True, "claude/x", "main")
    assert plan.ok is False
    assert plan.error
    assert "nenhuma pasta" in plan.error


def test_single_folder_no_worktree():
    plan = plan_from_dialog(["/tmp/a"], False, True, "ignored", "ignored")
    assert plan.ok
    assert plan.cwd == "/tmp/a"
    assert plan.extras == []
    assert plan.worktree_label == ""


def test_multi_folder_first_becomes_cwd():
    plan = plan_from_dialog(["/a", "/b", "/c"], False, True, "", "")
    assert plan.cwd == "/a"
    assert plan.extras == ["/b", "/c"]


def test_isolate_with_new_branch_calls_creator():
    seen = {}
    def fake_worktree(cwd, branch, base, create_branch=True):
        seen["args"] = (cwd, branch, base, create_branch)
        return True, "", Path("/tmp/wt-x")
    plan = plan_from_dialog(
        ["/repo"], True, True, "feature/x", "main",
        worktree_creator=fake_worktree,
    )
    assert plan.ok
    assert seen["args"] == ("/repo", "feature/x", "main", True)
    assert plan.cwd == "/tmp/wt-x"
    assert plan.worktree_label == " · feature/x"


def test_isolate_with_existing_branch_drops_base():
    """Quando create_branch=False, base não deve ser passada — o worktree
    faz checkout da existente."""
    seen = {}
    def fake_worktree(cwd, branch, base, create_branch=True):
        seen["args"] = (cwd, branch, base, create_branch)
        return True, "", Path("/tmp/wt-y")
    plan_from_dialog(
        ["/repo"], True, False, "existing-branch", "main",
        worktree_creator=fake_worktree,
    )
    assert seen["args"] == ("/repo", "existing-branch", None, False)


def test_isolate_with_empty_branch_errors():
    plan = plan_from_dialog(["/repo"], True, True, "   ", "main")
    assert not plan.ok
    assert "branch" in plan.error.lower()


def test_isolate_worktree_failure_propagates():
    def fake_worktree(*_args, **_kwargs):
        return False, "remote tem mudança não-resolvida", Path("/tmp")
    plan = plan_from_dialog(
        ["/repo"], True, True, "claude/x", "main",
        worktree_creator=fake_worktree,
    )
    assert not plan.ok
    assert "worktree falhou" in plan.error
    assert "remote tem mudança" in plan.error


def test_extras_preserved_after_worktree():
    """Worktree muda só o cwd; as outras pastas continuam como extras."""
    def fake_worktree(cwd, branch, base, create_branch=True):
        return True, "", Path("/tmp/wt")
    plan = plan_from_dialog(
        ["/a", "/b", "/c"], True, True, "br/x", "main",
        worktree_creator=fake_worktree,
    )
    assert plan.cwd == "/tmp/wt"
    assert plan.extras == ["/b", "/c"]


def test_build_argv_minimal():
    argv = build_claude_argv("claude", [], [], "")
    assert argv == ["claude"]


def test_build_argv_extra_args():
    argv = build_claude_argv("claude", ["--dangerously-skip"], [], "")
    assert argv == ["claude", "--dangerously-skip"]


def test_build_argv_resume():
    argv = build_claude_argv("claude", [], [], "abc-123")
    assert argv == ["claude", "--resume", "abc-123"]


def test_build_argv_with_extras():
    argv = build_claude_argv("claude", [], ["/a", "/b"], "")
    assert argv == ["claude", "--add-dir", "/a", "--add-dir", "/b"]


def test_build_argv_resume_and_extras():
    argv = build_claude_argv("claude", [], ["/a"], "sess")
    assert argv == ["claude", "--resume", "sess", "--add-dir", "/a"]
