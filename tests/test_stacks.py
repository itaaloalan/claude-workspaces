from claude_workspaces.stacks import (
    STACK_GLOBS,
    STACK_INDICATORS,
    STACK_LABEL,
    STACK_TO_IDE,
    detect_stacks,
)


def test_no_folders():
    assert detect_stacks([]) == set()


def test_nonexistent_folder_ignored(tmp_path):
    fake = tmp_path / "does-not-exist"
    assert detect_stacks([str(fake)]) == set()


def test_file_path_ignored(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert detect_stacks([str(f)]) == set()


def test_detects_python_by_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_stacks([str(tmp_path)]) == {"python"}


def test_detects_python_by_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()")
    assert detect_stacks([str(tmp_path)]) == {"python"}


def test_detects_java_by_pom(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    assert detect_stacks([str(tmp_path)]) == {"java"}


def test_detects_java_by_gradle_kts(tmp_path):
    (tmp_path / "build.gradle.kts").write_text("")
    assert detect_stacks([str(tmp_path)]) == {"java"}


def test_detects_web_by_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert detect_stacks([str(tmp_path)]) == {"web"}


def test_detects_csharp_by_csproj_glob(tmp_path):
    (tmp_path / "App.csproj").write_text("<Project/>")
    assert detect_stacks([str(tmp_path)]) == {"csharp"}


def test_detects_csharp_by_sln_glob(tmp_path):
    (tmp_path / "MySolution.sln").write_text("")
    assert detect_stacks([str(tmp_path)]) == {"csharp"}


def test_detects_multiple_stacks_same_folder(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "App.csproj").write_text("")
    assert detect_stacks([str(tmp_path)]) == {"python", "web", "csharp"}


def test_aggregates_across_folders(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "pom.xml").write_text("")
    (b / "pyproject.toml").write_text("")
    assert detect_stacks([str(a), str(b)]) == {"java", "python"}


def test_constants_have_labels_and_ides():
    """Garante que toda stack detectável tem label e mapeamento de IDE."""
    all_stacks = set(STACK_INDICATORS) | set(STACK_GLOBS)
    for stack in all_stacks:
        assert stack in STACK_LABEL, f"falta label para {stack}"
        assert stack in STACK_TO_IDE, f"falta IDE para {stack}"
