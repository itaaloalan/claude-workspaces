"""Regressão: o log ao vivo do runner tem que aparecer no console.

O lazy-load do console (1.0.3) adicionou um gate `_live` ao TerminalBridge
(nasce desligado; quem liga é go_live()). O TerminalWidget chama go_live ao
abrir, mas o RunnerWidget — que tem view eager — ficou sem destravar, então
todo output ao vivo do PTY era descartado e só os emits diretos (banner)
apareciam. Este teste fixa que o frontend ficando pronto destrava o gate e
replaya o buffer.
"""

from claude_workspaces.models import RunnerConfig
from claude_workspaces.ui.runner_widget import RunnerWidget


def test_bridge_ready_goes_live_and_replays(qapp):
    w = RunnerWidget(RunnerConfig(name="glassfish-ogpms", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        # Antes do frontend carregar: gate fechado (output ao vivo descartado).
        assert w.bridge._live is False

        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
        w._log_buf = "linha-de-log\n"

        # Simula o xterm.js do runner sinalizando que ficou pronto.
        w._on_bridge_ready()

        # Gate destravado + replay do que estava bufferizado no _log_buf.
        assert w.bridge._live is True
        assert any(b"linha-de-log" in e for e in emitted)
    finally:
        w.terminate()
        w.deleteLater()


def test_live_pty_output_passes_after_ready(qapp):
    """Depois de ready, um chunk do PTY chega ao terminal (não fica gated)."""
    w = RunnerWidget(RunnerConfig(name="ogpms-xhtml-watch", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        w._on_bridge_ready()
        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
        # Chunk como se viesse do PTY (passa pelo _on_pty_output do bridge).
        w.session.output_received.emit(b"compilando xhtml...\n")
        assert any(b"compilando xhtml" in e for e in emitted)
    finally:
        w.terminate()
        w.deleteLater()


# ---------- effective_cwd: runner de console segue o worktree (com subdir) ----

def test_console_runner_remaps_pinned_cwd_into_worktree(qapp, tmp_path):
    """runner.cwd fixo num subdir do checkout principal + apontamento (last_cwd)
    pra RAIZ do worktree → effective_cwd remapeia pro MESMO subdir dentro do
    worktree (não a raiz, onde não há .sln/package.json)."""
    import subprocess
    from pathlib import Path

    from claude_workspaces.git_worktree import add_worktree

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(args, cwd=repo, check=True)
    (repo / "src" / "web").mkdir(parents=True)
    (repo / "src" / "web" / "package.json").write_text("{}\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True)
    ok, msg, wt = add_worktree(str(repo), "feat/x")
    assert ok, msg

    rc = RunnerConfig(
        name="web", start_cmd="pnpm dev",
        cwd=str(repo / "src" / "web"),
        last_cwd=str(wt),  # apontado pra RAIZ do worktree (caso do bug)
    )
    w = RunnerWidget(rc, default_cwd=str(repo))
    try:
        assert w.effective_cwd() == str(Path(wt) / "src" / "web")
    finally:
        w.terminate()
        w.deleteLater()


def test_runner_without_worktree_keeps_pinned_cwd(qapp, tmp_path):
    """Sem worktree apontado, effective_cwd fica no cwd fixo (sem remap)."""
    import subprocess
    from pathlib import Path

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(args, cwd=repo, check=True)
    (repo / "src" / "web").mkdir(parents=True)
    (repo / "src" / "web" / "package.json").write_text("{}\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True)

    rc = RunnerConfig(name="web", start_cmd="pnpm dev", cwd=str(repo / "src" / "web"))
    w = RunnerWidget(rc, default_cwd=str(repo))
    try:
        assert w.effective_cwd() == str(Path(repo) / "src" / "web")
    finally:
        w.terminate()
        w.deleteLater()
