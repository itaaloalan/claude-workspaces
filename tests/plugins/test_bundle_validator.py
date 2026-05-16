"""Testes da validação de layout (seção 2 da spec)."""

from __future__ import annotations

from claude_workspaces.plugins import load_manifest
from claude_workspaces.plugins.bundle_validator import validate_layout


def _layout_errs(bundle):
    return validate_layout(bundle, load_manifest(bundle))


def test_valid_bundle_has_no_layout_errors(make_bundle):
    bundle = make_bundle()
    assert _layout_errs(bundle) == []


def test_readme_too_short(make_bundle):
    bundle = make_bundle(readme="curto")
    errs = _layout_errs(bundle)
    assert any("README" in e and "curto" in e for e in errs)


def test_readme_missing(make_bundle):
    bundle = make_bundle()
    (bundle / "README.md").unlink()
    errs = _layout_errs(bundle)
    assert any("README.md ausente" in e for e in errs)


def test_js_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"src/hooks/leak.js": "console.log(1)"})
    errs = _layout_errs(bundle)
    assert any(".js não é permitido" in e for e in errs)


def test_ts_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"src/hooks/leak.ts": "// ts"})
    errs = _layout_errs(bundle)
    assert any(".ts não é permitido" in e for e in errs)


def test_pyc_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"src/hooks/leak.pyc": "x"})
    errs = _layout_errs(bundle)
    assert any(".pyc não é permitido" in e for e in errs)


def test_pyproject_rejected(make_bundle):
    bundle = make_bundle(extra_files={"pyproject.toml": "[project]"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_setup_py_rejected(make_bundle):
    bundle = make_bundle(extra_files={"setup.py": "from setuptools import setup"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_pycache_rejected(make_bundle):
    bundle = make_bundle(extra_files={"src/hooks/__pycache__/x.pyc": "x"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_node_modules_rejected(make_bundle):
    bundle = make_bundle(extra_files={"node_modules/x/index.py": "# x"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_random_top_level_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"junk.md": "x"})
    errs = _layout_errs(bundle)
    assert any("top-level" in e for e in errs)


def test_src_must_have_subdir(make_bundle):
    bundle = make_bundle(extra_files={"src/loose.py": "x = 1"})
    errs = _layout_errs(bundle)
    assert any("src/" in e and "use src/commands" in e for e in errs)


def test_src_init_py_allowed(make_bundle):
    # make_bundle já cria src/__init__.py por default — nenhum erro
    assert _layout_errs(make_bundle()) == []


def test_unknown_src_subdir(make_bundle):
    bundle = make_bundle(extra_files={"src/utils/x.py": "x = 1"})
    errs = _layout_errs(bundle)
    assert any("src/utils" in e for e in errs)


def test_test_must_use_test_py_convention(make_bundle):
    bundle = make_bundle(extra_files={"tests/helper.py": "# not a test"})
    errs = _layout_errs(bundle)
    assert any("test_" in e for e in errs)


def test_test_init_py_allowed(make_bundle):
    bundle = make_bundle(extra_files={"tests/__init__.py": ""})
    assert _layout_errs(bundle) == []


def test_asset_extension_restricted(make_bundle):
    bundle = make_bundle(extra_files={"assets/icon.jpg": "x"})
    errs = _layout_errs(bundle)
    assert any("assets/" in e for e in errs)


def test_handler_file_must_exist(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {"event": "workspace.opened", "handler": "./src/hooks/missing.py"}
                ]
            }
        },
        skip_default_handler=True,
    )
    errs = _layout_errs(bundle)
    assert any("Handler" in e and "missing.py" in e for e in errs)


def test_panel_icon_must_exist(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "panels": [
                    {
                        "id": "p",
                        "title": "P",
                        "slot": "sidebar-top",
                        "handler": "./src/panels/p.py",
                        "icon": "./assets/missing.svg",
                    }
                ]
            }
        },
        extra_files={
            "src/panels/__init__.py": "",
            "src/panels/p.py": "def handler(ctx): pass\n",
        },
        skip_default_handler=True,
    )
    errs = _layout_errs(bundle)
    assert any("Icon" in e and "missing.svg" in e for e in errs)
