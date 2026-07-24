"""Testes da árvore de changes do GitPanel (coluna única, modo flat).

Chamam `_apply_statuses` direto com GitStatus fabricados — sem subprocess
git — pra validar o shape da árvore, a coleta de checked/unchecked e o
update in-place dos ±linhas quando o fingerprint não muda.
"""

from PySide6.QtCore import Qt

from claude_workspaces.git_status import GitFile, GitStatus
from claude_workspaces.ui.git_panel import (
    _STATS_ROLE,
    T_FILE,
    T_FOLDER,
    T_GROUP,
    T_REPO,
    GitPanel,
)


def _make_panel(folders: list[str]) -> GitPanel:
    panel = GitPanel()
    # Atalho: injeta as pastas sem disparar refresh() (que rodaria git real).
    panel._folders_override = list(folders)
    return panel


def _apply(panel: GitPanel, statuses: dict, numstats: dict | None = None) -> None:
    panel._status_epoch += 1
    panel._apply_statuses(panel._status_epoch, statuses, numstats or {}, {})


def _status(folder: str, files: list[GitFile], branch: str = "main") -> GitStatus:
    return GitStatus(folder=folder, is_repo=True, branch=branch, files=files)


def _walk(parent):
    for i in range(parent.childCount()):
        child = parent.child(i)
        yield child
        yield from _walk(child)


def _items_of_type(panel: GitPanel, t: str):
    return [
        it
        for it in _walk(panel._tree.invisibleRootItem())
        if (it.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == t
    ]


def _top_level_types(panel: GitPanel) -> list[str]:
    return [
        (
            panel._tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or {}
        ).get("type")
        for i in range(panel._tree.topLevelItemCount())
    ]


def test_feed_removido_e_splitter_com_3_paineis(qapp):
    panel = _make_panel([])
    assert not hasattr(panel, "_feed")
    assert panel._main_split.count() == 3
    assert panel._tree.columnCount() == 1


def test_single_repo_monta_grupos_na_raiz(qapp, tmp_path):
    folder = str(tmp_path)
    files = [
        GitFile(" M", "src/app/main.py"),
        GitFile(" M", "src/app/util.py"),
        GitFile("??", "notes.txt"),
    ]
    panel = _make_panel([folder])
    _apply(panel, {folder: _status(folder, files)})

    types = _top_level_types(panel)
    assert T_REPO not in types
    assert types.count(T_GROUP) == 2  # Changes + Unversioned Files

    # Separador de pasta guarda o caminho relativo COMPLETO no texto
    # (o elide é responsabilidade do delegate, não do dado).
    seps = _items_of_type(panel, T_FOLDER)
    assert [s.text(0) for s in seps] == ["src/app"]

    # Arquivo mostra só o basename
    file_items = _items_of_type(panel, T_FILE)
    assert sorted(f.text(0) for f in file_items) == [
        "main.py",
        "notes.txt",
        "util.py",
    ]


def test_multi_repo_mantem_nivel_de_repo(qapp, tmp_path):
    fa = str(tmp_path / "repo_a")
    fb = str(tmp_path / "repo_b")
    panel = _make_panel([fa, fb])
    _apply(
        panel,
        {
            fa: _status(fa, [GitFile(" M", "a.py")]),
            fb: _status(fb, [GitFile(" M", "b.py")], branch="dev"),
        },
    )
    assert _top_level_types(panel) == [T_REPO, T_REPO]


def test_collect_checked_files_por_folder(qapp, tmp_path):
    fa = str(tmp_path / "repo_a")
    fb = str(tmp_path / "repo_b")
    panel = _make_panel([fa, fb])
    _apply(
        panel,
        {
            fa: _status(fa, [GitFile(" M", "a.py"), GitFile(" M", "x.py")]),
            fb: _status(fb, [GitFile(" M", "b.py")]),
        },
    )
    assert panel._collect_checked_files() == {
        fa: ["a.py", "x.py"],
        fb: ["b.py"],
    }

    # Desmarca um arquivo → sai do dict
    target = next(
        it
        for it in _items_of_type(panel, T_FILE)
        if it.data(0, Qt.ItemDataRole.UserRole)["rel_path"] == "x.py"
    )
    target.setCheckState(0, Qt.CheckState.Unchecked)
    assert panel._collect_checked_files() == {fa: ["a.py"], fb: ["b.py"]}


def test_collect_checked_files_no_modo_flat(qapp, tmp_path):
    folder = str(tmp_path)
    panel = _make_panel([folder])
    _apply(panel, {folder: _status(folder, [GitFile(" M", "a.py")])})
    assert panel._collect_checked_files() == {folder: ["a.py"]}


def test_unchecked_preservado_apos_rebuild(qapp, tmp_path):
    folder = str(tmp_path)
    files = [GitFile(" M", "a.py"), GitFile(" M", "b.py")]
    panel = _make_panel([folder])
    _apply(panel, {folder: _status(folder, files)})

    target = next(
        it
        for it in _items_of_type(panel, T_FILE)
        if it.data(0, Qt.ItemDataRole.UserRole)["rel_path"] == "a.py"
    )
    target.setCheckState(0, Qt.CheckState.Unchecked)

    # Mesmo fluxo do refresh(): coleta unchecked da árvore atual e reaplica
    # num rebuild (fingerprint muda porque a branch mudou).
    prev: dict[str, set[str]] = {}
    panel._collect_unchecked_files(panel._tree.invisibleRootItem(), prev)
    assert prev == {folder: {"a.py"}}
    panel._prev_unchecked = prev
    _apply(panel, {folder: _status(folder, files, branch="dev")})

    states = {
        it.data(0, Qt.ItemDataRole.UserRole)["rel_path"]: it.checkState(0)
        for it in _items_of_type(panel, T_FILE)
    }
    assert states["a.py"] == Qt.CheckState.Unchecked
    assert states["b.py"] == Qt.CheckState.Checked


def test_stats_atualizam_in_place_sem_rebuild(qapp, tmp_path):
    folder = str(tmp_path)
    files = [GitFile(" M", "a.py")]
    panel = _make_panel([folder])
    _apply(panel, {folder: _status(folder, files)}, {folder: {"a.py": (1, 0)}})

    item = _items_of_type(panel, T_FILE)[0]
    assert item.data(0, _STATS_ROLE) == (1, 0)

    # Mesmo status (fingerprint igual) com numstat novo → sem rebuild
    # (mesmo objeto de item), mas _STATS_ROLE atualizado in-place.
    _apply(panel, {folder: _status(folder, files)}, {folder: {"a.py": (5, 2)}})
    same_item = _items_of_type(panel, T_FILE)[0]
    assert same_item is item
    assert same_item.data(0, _STATS_ROLE) == (5, 2)


def test_contador_mostra_arquivos_e_linhas(qapp, tmp_path):
    folder = str(tmp_path)
    panel = _make_panel([folder])
    _apply(
        panel,
        {folder: _status(folder, [GitFile(" M", "a.py"), GitFile(" M", "b.py")])},
        {folder: {"a.py": (3, 1), "b.py": (2, 0)}},
    )
    text = panel._counter.text()
    assert "2 arquivo(s)" in text
    assert "+5" in text
    assert "-1" in text
