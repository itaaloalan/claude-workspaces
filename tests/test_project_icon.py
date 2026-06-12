"""Testes da detecção de ícone real do projeto (services.project_icon)."""

from claude_workspaces.services.project_icon import (
    detect_project_icons,
    is_image_file,
)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n")  # conteúdo irrelevante; só precisa existir


def test_detect_root_favicon(tmp_path):
    _touch(tmp_path / "favicon.ico")
    hits = detect_project_icons(str(tmp_path))
    assert hits == [str(tmp_path / "favicon.ico")]


def test_detect_public_logo(tmp_path):
    _touch(tmp_path / "public" / "logo192.png")
    hits = detect_project_icons(str(tmp_path))
    assert str(tmp_path / "public" / "logo192.png") in hits


def test_root_favicon_ranks_before_public(tmp_path):
    _touch(tmp_path / "favicon.ico")
    _touch(tmp_path / "public" / "logo.png")
    hits = detect_project_icons(str(tmp_path))
    assert hits[0] == str(tmp_path / "favicon.ico")


def test_ignores_non_image_extensions(tmp_path):
    _touch(tmp_path / "favicon.txt")  # não é imagem
    assert detect_project_icons(str(tmp_path)) == []


def test_empty_for_missing_folder(tmp_path):
    assert detect_project_icons(str(tmp_path / "nope")) == []
    assert detect_project_icons("") == []
    assert detect_project_icons([]) == []


def test_multi_repo_folders_aggregated(tmp_path):
    a = tmp_path / "api"
    b = tmp_path / "web"
    _touch(a / "icon.png")
    _touch(b / "favicon.svg")
    hits = detect_project_icons([str(a), str(b)])
    assert str(a / "icon.png") in hits
    assert str(b / "favicon.svg") in hits


def test_dedup_preserves_order(tmp_path):
    _touch(tmp_path / "favicon.ico")
    # mesma pasta passada duas vezes não duplica
    hits = detect_project_icons([str(tmp_path), str(tmp_path)])
    assert hits.count(str(tmp_path / "favicon.ico")) == 1


def test_limit_caps_results(tmp_path):
    for i in range(20):
        _touch(tmp_path / "public" / f"logo{i}.png")
    hits = detect_project_icons(str(tmp_path), limit=5)
    assert len(hits) == 5


def test_is_image_file(tmp_path):
    img = tmp_path / "a.png"
    _touch(img)
    assert is_image_file(str(img)) is True
    assert is_image_file(str(tmp_path / "a.txt")) is False
    assert is_image_file("") is False
    assert is_image_file(str(tmp_path / "missing.png")) is False
