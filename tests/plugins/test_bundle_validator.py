"""Testes da validação de layout (seção 2 da spec)."""

from __future__ import annotations

import pytest

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


def test_readme_missing(make_bundle, tmp_path):
    bundle = make_bundle()
    (bundle / "README.md").unlink()
    errs = _layout_errs(bundle)
    assert any("README.md ausente" in e for e in errs)


def test_js_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"src/hooks/leak.js": "console.log(1)"})
    errs = _layout_errs(bundle)
    assert any(".js não é permitido" in e for e in errs)


def test_package_json_rejected(make_bundle):
    bundle = make_bundle(extra_files={"package.json": "{}"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_node_modules_rejected(make_bundle):
    bundle = make_bundle(extra_files={"node_modules/x/index.ts": "// x"})
    errs = _layout_errs(bundle)
    assert any("proibido" in e for e in errs)


def test_random_top_level_file_rejected(make_bundle):
    bundle = make_bundle(extra_files={"junk.md": "x"})
    errs = _layout_errs(bundle)
    assert any("top-level" in e for e in errs)


def test_src_must_have_subdir(make_bundle):
    bundle = make_bundle(extra_files={"src/loose.ts": "//"})
    errs = _layout_errs(bundle)
    assert any("src/" in e and "use src/commands" in e for e in errs)


def test_unknown_src_subdir(make_bundle):
    bundle = make_bundle(extra_files={"src/utils/x.ts": "//"})
    errs = _layout_errs(bundle)
    assert any("src/utils" in e for e in errs)


def test_test_must_use_test_ts_convention(make_bundle):
    bundle = make_bundle(extra_files={"tests/helper.ts": "//"})
    errs = _layout_errs(bundle)
    assert any("*.test.ts" in e for e in errs)


def test_asset_extension_restricted(make_bundle):
    bundle = make_bundle(extra_files={"assets/icon.jpg": "x"})
    errs = _layout_errs(bundle)
    assert any("assets/" in e for e in errs)


def test_handler_file_must_exist(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "hooks": [
                    {"event": "workspace.opened", "handler": "./src/hooks/missing.ts"}
                ]
            }
        },
        skip_default_handler=True,
    )
    errs = _layout_errs(bundle)
    assert any("Handler" in e and "missing.ts" in e for e in errs)


def test_panel_icon_must_exist(make_bundle):
    bundle = make_bundle(
        overrides={
            "extensions": {
                "panels": [
                    {
                        "id": "p",
                        "title": "P",
                        "slot": "sidebar-top",
                        "handler": "./src/panels/p.ts",
                        "icon": "./assets/missing.svg",
                    }
                ]
            }
        },
        extra_files={"src/panels/p.ts": "export default function(){}"},
        skip_default_handler=True,
    )
    errs = _layout_errs(bundle)
    assert any("Icon" in e and "missing.svg" in e for e in errs)
