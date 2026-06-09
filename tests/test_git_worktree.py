import subprocess

import pytest

from claude_workspaces.git_worktree import (
    add_worktree,
    list_local_branches,
    remove_worktree,
    resolve_git_dirs,
    translate_dir_for_repo,
    safe_dir_name,
    suggest_branch_name,
    worktree_base,
    worktree_path_for,
)


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _run(["git", "init", "-q", "-b", "main"], repo_path)
    _run(["git", "config", "user.email", "t@t"], repo_path)
    _run(["git", "config", "user.name", "t"], repo_path)
    (repo_path / "f.txt").write_text("hi\n")
    _run(["git", "add", "f.txt"], repo_path)
    _run(["git", "commit", "-q", "-m", "init"], repo_path)
    return repo_path


def test_safe_dir_name():
    assert safe_dir_name("simple") == "simple"
    assert safe_dir_name("with/slash") == "with_slash"
    assert safe_dir_name("claude/foo-bar") == "claude_foo-bar"
    assert safe_dir_name("a b c") == "a_b_c"


def test_suggest_branch_name_default():
    name = suggest_branch_name()
    assert name.startswith("claude/")


def test_suggest_branch_name_custom_prefix():
    name = suggest_branch_name("italo")
    assert name.startswith("italo/")


def test_suggest_branch_name_normalizes_prefix():
    assert suggest_branch_name("").startswith("claude/")
    assert suggest_branch_name(None).startswith("claude/")
    assert suggest_branch_name("italo/").startswith("italo/")


def test_worktree_path_for(repo):
    p = worktree_path_for(str(repo), "feature/x")
    assert p == worktree_base(str(repo)) / "feature_x"
    assert "repo.claude" in str(p)


def test_add_worktree_new_branch(repo):
    ok, msg, dest = add_worktree(str(repo), "feature/test", "main")
    assert ok, msg
    assert dest.exists()
    assert (dest / "f.txt").read_text() == "hi\n"
    # branch foi criada
    branches = list_local_branches(str(repo))
    assert "feature/test" in branches


def test_add_worktree_existing_branch(repo):
    # Cria branch primeiro
    _run(["git", "branch", "feature/existing"], repo)
    ok, msg, dest = add_worktree(
        str(repo), "feature/existing", None, create_branch=False
    )
    assert ok, msg
    assert dest.exists()


def test_add_worktree_existing_path_fails(repo):
    ok1, _, dest = add_worktree(str(repo), "branch1", "main")
    assert ok1
    ok2, msg, _ = add_worktree(str(repo), "branch1", "main")
    assert not ok2
    assert "já existe" in msg


def test_remove_worktree(repo):
    ok, _, dest = add_worktree(str(repo), "to-remove", "main")
    assert ok
    assert dest.exists()
    ok2, _ = remove_worktree(str(dest))
    assert ok2
    assert not dest.exists()


def test_remove_worktree_refuses_main_repo(repo):
    ok, msg = remove_worktree(str(repo))
    assert not ok
    assert "principal" in msg


def test_list_local_branches(repo):
    _run(["git", "branch", "feature/a"], repo)
    _run(["git", "branch", "bugfix/b"], repo)
    branches = list_local_branches(str(repo))
    assert "main" in branches
    assert "feature/a" in branches
    assert "bugfix/b" in branches


def test_resolve_git_dirs_repo_normal(repo):
    dirs = resolve_git_dirs(str(repo))
    assert dirs is not None
    git_dir, common_dir = dirs
    assert git_dir == common_dir == repo / ".git"


def test_resolve_git_dirs_worktree(repo):
    ok, _msg, dest = add_worktree(str(repo), "claude/wt-a")
    assert ok
    dirs = resolve_git_dirs(str(dest))
    assert dirs is not None
    git_dir, common_dir = dirs
    # git_dir privado da worktree; common compartilhado no repo principal
    assert git_dir != common_dir
    assert git_dir == (repo / ".git" / "worktrees" / git_dir.name).resolve()
    assert common_dir == (repo / ".git").resolve()
    assert (git_dir / "HEAD").is_file()
    assert (common_dir / "refs" / "heads").is_dir()


def test_resolve_git_dirs_nao_repo(tmp_path):
    assert resolve_git_dirs(str(tmp_path)) is None


def test_dirty_files_e_unpushed_commits(repo):
    from claude_workspaces.git_worktree import (
        dirty_files,
        unpushed_commits,
    )

    ok, msg, wt = add_worktree(str(repo), "feat/sujo", None, create_branch=True)
    assert ok, msg
    assert dirty_files(str(wt)) == []
    assert unpushed_commits(str(wt)) != []

    (wt / "novo.txt").write_text("x\n")
    sujos = dirty_files(str(wt))
    assert any("novo.txt" in ln for ln in sujos)


def test_delete_branch_so_mergeada(repo):
    from claude_workspaces.git_worktree import delete_branch

    _run(["git", "branch", "mergeada"], repo)
    ok, _ = delete_branch(str(repo), "mergeada")
    assert ok

    _run(["git", "checkout", "-q", "-b", "nao-mergeada"], repo)
    (repo / "g.txt").write_text("y\n")
    _run(["git", "add", "g.txt"], repo)
    _run(["git", "commit", "-q", "-m", "extra"], repo)
    _run(["git", "checkout", "-q", "main"], repo)
    ok, msg = delete_branch(str(repo), "nao-mergeada")
    assert not ok
    assert "nao-mergeada" in msg


# ---- translate_dir_for_repo (multi-repo) ------------------------------------


@pytest.fixture
def two_repos(tmp_path):
    """Dois repos independentes (map-api / map-web) no mesmo workspace."""
    repos = []
    for name in ("map-api", "map-web"):
        p = tmp_path / name
        p.mkdir()
        _run(["git", "init", "-q", "-b", "main"], p)
        _run(["git", "config", "user.email", "t@t"], p)
        _run(["git", "config", "user.name", "t"], p)
        (p / "f.txt").write_text("hi\n")
        _run(["git", "add", "f.txt"], p)
        _run(["git", "commit", "-q", "-m", "init"], p)
        repos.append(p)
    return repos


def test_translate_mesmo_repo_devolve_o_proprio_target(two_repos):
    api, _web = two_repos
    ok, _msg, wt = add_worktree(str(api), "fix/x")
    assert ok
    assert translate_dir_for_repo(str(wt), str(api)) == str(wt)


def test_translate_outro_repo_com_worktree_de_mesma_branch(two_repos):
    api, web = two_repos
    ok, _m, wt_api = add_worktree(str(api), "fix/x")
    assert ok
    ok, _m, wt_web = add_worktree(str(web), "fix/x")
    assert ok
    from pathlib import Path
    out = translate_dir_for_repo(str(wt_api), str(web))
    assert Path(out).resolve() == Path(wt_web).resolve()


def test_translate_outro_repo_sem_worktree_da_branch(two_repos):
    api, web = two_repos
    ok, _m, wt_api = add_worktree(str(api), "fix/so-na-api")
    assert ok
    assert translate_dir_for_repo(str(wt_api), str(web)) == ""


def test_translate_mesma_branch_no_checkout_principal(two_repos):
    """Console no repo principal da api (branch main) → runner do web cai
    no checkout principal do web (que também está na main)."""
    api, web = two_repos
    from pathlib import Path
    out = translate_dir_for_repo(str(api), str(web))
    assert Path(out).resolve() == Path(web).resolve()


def test_translate_entradas_invalidas(two_repos, tmp_path):
    api, _web = two_repos
    nao_git = tmp_path / "nao-git"
    nao_git.mkdir()
    assert translate_dir_for_repo("", str(api)) == ""
    assert translate_dir_for_repo(str(api), "") == ""
    assert translate_dir_for_repo(str(nao_git), str(api)) == ""
    assert translate_dir_for_repo(str(api), str(nao_git)) == ""


def test_translate_repo_folder_em_subdir(repo):
    """Pasta do workspace é um SUBDIR do repo (ex.: sipepro .../sipe/sipe/src,
    sem .git ali). Antes resolve_git_dirs(subdir)=None → "" → o runner ficava na
    main; agora resolve a raiz via repo_root e devolve o worktree."""
    src = repo / "src"
    src.mkdir()
    (src / "f.txt").write_text("x\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "src"], repo)
    ok, msg, wt = add_worktree(str(repo), "feat/x")
    assert ok, msg
    assert translate_dir_for_repo(str(wt), str(src)) == str(wt)


def test_translate_target_em_subdir_do_worktree(repo):
    """target = subdir DENTRO do worktree (caso 'abrir console em worktree' com
    offset). Mesmo repo → devolve o próprio target (com offset); o
    remap_into_worktree recompõe o subdir depois."""
    src = repo / "src"
    src.mkdir()
    (src / "f.txt").write_text("x\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "src"], repo)
    ok, msg, wt = add_worktree(str(repo), "feat/y")
    assert ok, msg
    from pathlib import Path
    wt_src = Path(wt) / "src"
    assert translate_dir_for_repo(str(wt_src), str(src)) == str(wt_src)


# ---------- remap_into_worktree (runner de console segue o worktree) ----------

def test_remap_into_worktree_preserva_subdir(repo):
    from claude_workspaces.git_worktree import remap_into_worktree
    sub = repo / "src" / "api"
    sub.mkdir(parents=True)
    (sub / "main.py").write_text("x\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "api"], repo)
    ok, msg, wt = add_worktree(str(repo), "feat/x")
    assert ok, msg
    out = remap_into_worktree(str(sub), str(wt))
    assert out == str((wt / "src" / "api").resolve())


def test_remap_mesmo_checkout_vazio(repo):
    from claude_workspaces.git_worktree import remap_into_worktree
    # worktree_dir == o próprio checkout → nada a remapear
    assert remap_into_worktree(str(repo), str(repo)) == ""


def test_remap_repo_diferente_vazio(repo, tmp_path):
    from claude_workspaces.git_worktree import remap_into_worktree
    other = tmp_path / "other"
    other.mkdir()
    _run(["git", "init", "-q", "-b", "main"], other)
    _run(["git", "config", "user.email", "t@t"], other)
    _run(["git", "config", "user.name", "t"], other)
    (other / "f.txt").write_text("y\n")
    _run(["git", "add", "."], other)
    _run(["git", "commit", "-q", "-m", "i"], other)
    ok, msg, wt = add_worktree(str(repo), "feat/y")
    assert ok, msg
    # path de OUTRO repo + worktree do `repo` → repos diferentes → "" (fica no main)
    assert remap_into_worktree(str(other), str(wt)) == ""


# ---------- same_repo ----------

def test_same_repo_raiz_subdir_worktree(repo):
    from claude_workspaces.git_worktree import same_repo
    sub = repo / "src" / "x"
    sub.mkdir(parents=True)
    (sub / "f.txt").write_text("x\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-q", "-m", "x"], repo)
    ok, msg, wt = add_worktree(str(repo), "feat/sr")
    assert ok, msg
    # raiz vs subdir vs worktree → mesmo repo
    assert same_repo(str(repo), str(sub)) is True
    assert same_repo(str(sub), str(wt)) is True
    assert same_repo(str(repo), str(wt)) is True


def test_same_repo_repos_diferentes_e_nao_git(two_repos, tmp_path):
    from claude_workspaces.git_worktree import same_repo
    api, web = two_repos
    assert same_repo(str(api), str(web)) is False
    nao_git = tmp_path / "plain"
    nao_git.mkdir()
    assert same_repo(str(api), str(nao_git)) is False
    assert same_repo("", str(api)) is False
