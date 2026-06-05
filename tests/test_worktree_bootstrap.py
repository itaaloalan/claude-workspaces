"""Testes do sync de configs locais repo principal → worktree novo."""

from claude_workspaces.services.launch_planner import plan_from_dialog
from claude_workspaces.services.worktree_bootstrap import sync_local_configs


def _mk(tmp_path):
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    repo.mkdir()
    wt.mkdir()
    return repo, wt


def test_config_divergente_eh_copiada(tmp_path):
    repo, wt = _mk(tmp_path)
    rel = "src/main/resources/application-dev.yml"
    (repo / rel).parent.mkdir(parents=True)
    (repo / rel).write_text("url: jdbc:postgresql://localhost:5432/map_pocos\n")
    (wt / rel).parent.mkdir(parents=True)
    (wt / rel).write_text("url: jdbc:postgresql://srv-antigo:5432/map\n")
    copied = sync_local_configs(str(repo), str(wt))
    assert rel in copied
    assert "map_pocos" in (wt / rel).read_text()


def test_config_identica_nao_eh_copiada(tmp_path):
    repo, wt = _mk(tmp_path)
    for base in (repo, wt):
        (base / ".env").write_text("PORT=3000\n")
    assert sync_local_configs(str(repo), str(wt)) == []


def test_env_so_no_principal_eh_criado_no_worktree(tmp_path):
    repo, wt = _mk(tmp_path)
    (repo / ".env.local").write_text("DB=map_local\n")
    copied = sync_local_configs(str(repo), str(wt))
    assert ".env.local" in copied
    assert (wt / ".env.local").read_text() == "DB=map_local\n"


def test_arquivo_so_no_worktree_fica_intocado(tmp_path):
    repo, wt = _mk(tmp_path)
    (wt / "appsettings.json").write_text('{"db": "x"}')
    assert sync_local_configs(str(repo), str(wt)) == []
    assert (wt / "appsettings.json").read_text() == '{"db": "x"}'


def test_diretorios_invalidos_sao_noop(tmp_path):
    assert sync_local_configs(str(tmp_path / "nada"), str(tmp_path)) == []
    assert sync_local_configs(str(tmp_path), str(tmp_path / "nada")) == []


def test_plan_from_dialog_sincroniza_sem_explodir(tmp_path):
    """worktree_creator fake + repo sem configs casáveis → plano ok."""
    repo, wt = _mk(tmp_path)

    def fake_creator(repo_path, branch, base, create_branch=True):
        return True, "", wt

    plan = plan_from_dialog(
        [str(repo)], True, True, "feat/x", "main",
        worktree_creator=fake_creator,
    )
    assert plan.ok and plan.is_worktree
    assert plan.cwd == str(wt)


def test_plan_from_dialog_copia_config(tmp_path):
    repo, wt = _mk(tmp_path)
    (repo / ".env").write_text("DB=map_pocos\n")

    def fake_creator(repo_path, branch, base, create_branch=True):
        return True, "", wt

    plan = plan_from_dialog(
        [str(repo)], True, True, "feat/x", "main",
        worktree_creator=fake_creator,
    )
    assert plan.ok
    assert (wt / ".env").read_text() == "DB=map_pocos\n"
