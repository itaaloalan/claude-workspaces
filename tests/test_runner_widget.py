"""Regressão: o log ao vivo do runner tem que aparecer no console.

O lazy-load do console (1.0.3) adicionou um gate `_live` ao TerminalBridge
(nasce desligado; quem liga é go_live()). O TerminalWidget chama go_live ao
abrir, mas o RunnerWidget — que tem view eager — ficou sem destravar, então
todo output ao vivo do PTY era descartado e só os emits diretos (banner)
apareciam. Este teste fixa que o frontend ficando pronto destrava o gate e
replaya o buffer.
"""

import os

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
    """Depois de ready, um chunk do PTY chega ao terminal (não fica gated).
    O output ao vivo agora é coalescido (janela de 16ms) — o emit sai no
    flush do timer, não inline."""
    import time as _time

    w = RunnerWidget(RunnerConfig(name="ogpms-xhtml-watch", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        w._on_bridge_ready()
        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))
        # Chunk como se viesse do PTY (passa pelo _on_pty_output do bridge).
        w.session.output_received.emit(b"compilando xhtml...\n")
        # Coalescido: nada inline; o flush vem com o timer de 16ms.
        assert not any(b"compilando xhtml" in e for e in emitted)
        deadline = _time.monotonic() + 2.0
        while not emitted and _time.monotonic() < deadline:
            qapp.processEvents()
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


def test_cross_repo_override_is_ignored(qapp, tmp_path):
    """runner.cwd no repo A (ex.: manager) + last_cwd apontando pro worktree do
    repo B (ex.: 'apontar todos pro worktree do sipe') → o override de outro
    repo é descartado e o runner fica no próprio cwd (main do repo A), não na
    raiz do worktree errado."""
    import subprocess
    from pathlib import Path

    from claude_workspaces.git_worktree import add_worktree

    def _mkrepo(name):
        p = tmp_path / name
        (p / "src").mkdir(parents=True)
        for args in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(args, cwd=p, check=True)
        (p / "src" / "proj.txt").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=p, check=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=p, check=True)
        return p

    repo_a = _mkrepo("manager")   # repo do runner
    repo_b = _mkrepo("sipe")      # repo do console (com worktree)
    ok, msg, wt_b = add_worktree(str(repo_b), "feat/x")
    assert ok, msg

    rc = RunnerConfig(
        name="manager", start_cmd="dotnet run",
        cwd=str(repo_a / "src"),
        last_cwd=str(wt_b),  # worktree de OUTRO repo (apontar-todos)
    )
    w = RunnerWidget(rc, default_cwd=str(repo_a))
    try:
        assert w.effective_cwd() == str(repo_a / "src")
    finally:
        w.terminate()
        w.deleteLater()


# ---------- hot reload: chip visível no console do runner ---------------

def test_hot_reload_chip_hidden_when_flag_off(qapp, tmp_path):
    w = RunnerWidget(RunnerConfig(name="t", start_cmd="true"), default_cwd=str(tmp_path))
    try:
        assert w._hot_reload_btn.isHidden() is True
    finally:
        w.terminate()
        w.deleteLater()


def test_hot_reload_chip_visible_idle_then_watching(qapp, tmp_path, qtbot):
    """Ligado mas parado: chip visível, mas não no estilo "observando"
    (watcher só existe com o runner rodando). Ao simular o runner rodando e
    montar o watcher, o chip reflete o estado ativo."""
    rc = RunnerConfig(name="glassfish-ogpms", start_cmd="true", hot_reload=True)
    w = RunnerWidget(rc, default_cwd=str(tmp_path))
    try:
        assert w._hot_reload_btn.isHidden() is False
        assert "ligado" in w._hot_reload_btn.toolTip()

        w._state = "running"
        w._start_hot_reload_watch(str(tmp_path))
        qtbot.waitUntil(lambda: w._hot_reload_watcher is not None, timeout=2000)
        assert w._hot_reload_btn.isHidden() is False
        assert "ativo" in w._hot_reload_btn.toolTip()
    finally:
        w.terminate()
        w.deleteLater()


def test_hot_reload_chip_click_toggles_flag(qapp, tmp_path):
    w = RunnerWidget(RunnerConfig(name="t", start_cmd="true"), default_cwd=str(tmp_path))
    try:
        assert w._runner.hot_reload is False
        emitted = []
        w.hot_reload_changed.connect(emitted.append)

        w._toggle_hot_reload()
        assert w._runner.hot_reload is True
        assert w._hot_reload_btn.isHidden() is False
        assert emitted == [True]

        w._toggle_hot_reload()
        assert w._runner.hot_reload is False
        assert w._hot_reload_btn.isHidden() is True
        assert emitted == [True, False]
    finally:
        w.terminate()
        w.deleteLater()


# ---------- hot reload: restart automático ao detectar .java/.xhtml -----

def test_hot_reload_restarts_on_java_change(qapp, tmp_path, qtbot):
    """hot_reload=True, runner "rodando": tocar um .java no cwd observado
    dispara restart() sozinho, depois do debounce. Simula o watcher via
    `_on_hot_reload_dir_changed` diretamente (evita depender do timing real
    de inotify em CI) — o que este teste garante é a lógica nova: snapshot
    de mtimes por padrão, debounce e chamada de restart()."""
    (tmp_path / "Foo.java").write_text("class Foo {}")
    rc = RunnerConfig(name="glassfish-ogpms", start_cmd="true", hot_reload=True)
    w = RunnerWidget(rc, default_cwd=str(tmp_path))
    try:
        w._state = "running"  # simula processo de pé sem forkar de verdade
        restarts = []
        w.restart = lambda: restarts.append(1)

        w._start_hot_reload_watch(str(tmp_path))
        qtbot.waitUntil(lambda: w._hot_reload_watcher is not None, timeout=2000)
        assert any(p.endswith("Foo.java") for p in w._hot_reload_mtimes)

        # Toca o .java com mtime no futuro — determinístico mesmo em FS com
        # resolução de mtime de 1s (sem precisar de time.sleep real).
        java_path = tmp_path / "Foo.java"
        future = java_path.stat().st_mtime + 5
        os.utime(java_path, (future, future))

        w._on_hot_reload_dir_changed(str(tmp_path))
        qtbot.waitUntil(lambda: len(restarts) == 1, timeout=2000)
    finally:
        w.terminate()
        w.deleteLater()


def test_hot_reload_ignores_unrelated_file_change(qapp, tmp_path, qtbot):
    """Arquivo que não casa .java/.xhtml (ex: .log de build) não deve
    disparar restart — só o padrão observado importa."""
    (tmp_path / "Foo.java").write_text("class Foo {}")
    rc = RunnerConfig(name="glassfish-ogpms", start_cmd="true", hot_reload=True)
    w = RunnerWidget(rc, default_cwd=str(tmp_path))
    try:
        w._state = "running"
        restarts = []
        w.restart = lambda: restarts.append(1)

        w._start_hot_reload_watch(str(tmp_path))
        qtbot.waitUntil(lambda: w._hot_reload_watcher is not None, timeout=2000)

        (tmp_path / "build.log").write_text("linha irrelevante")
        w._on_hot_reload_dir_changed(str(tmp_path))
        # Dá tempo do debounce (800ms) rodar e confirma que NADA disparou.
        qtbot.wait(1000)
        assert restarts == []
    finally:
        w.terminate()
        w.deleteLater()


def test_hot_reload_disabled_does_not_restart(qapp, tmp_path, qtbot):
    """hot_reload=False (default): não monta watcher nenhum."""
    rc = RunnerConfig(name="glassfish-ogpms", start_cmd="true")
    w = RunnerWidget(rc, default_cwd=str(tmp_path))
    try:
        w._state = "running"
        w._start_hot_reload_watch(str(tmp_path))
        # Como hot_reload é False, _on_hot_reload_dirs_ready descarta o
        # resultado do scan assíncrono e o watcher nunca é montado.
        qtbot.wait(300)
        assert w._hot_reload_watcher is None
    finally:
        w.terminate()
        w.deleteLater()


def test_deploy_warning_logs_once_despite_on_off_flicker(qapp):
    """Regressão: `served_mismatch()` roda a cada ~3s num subprocess (ss/lsof)
    e pode oscilar True/False por flakiness de detecção mesmo com o deploy
    permanecendo fora do worktree o tempo todo. Antes, cada oscilação para
    True reimprimia a linha de aviso no log do runner ("fica toda hora").
    Agora só a primeira transição loga; o chip ainda reflete o estado atual."""
    w = RunnerWidget(RunnerConfig(name="sipe-manager", start_cmd="echo hi"),
                     default_cwd="/tmp")
    try:
        emitted: list[bytes] = []
        w.bridge.output_to_terminal.connect(lambda b: emitted.append(bytes(b)))

        w.set_deploy_warning(True, "/outro/worktree")
        w.set_deploy_warning(False)
        w.set_deploy_warning(True, "/outro/worktree")
        w.set_deploy_warning(False)
        w.set_deploy_warning(True, "/outro/worktree")

        warn_lines = [e for e in emitted if b"deploy fora do worktree" in e]
        assert len(warn_lines) == 1
        # Chip continua refletindo o estado atual mesmo sem reimprimir o log.
        assert w._deploy_warned is True
    finally:
        w.terminate()
        w.deleteLater()
