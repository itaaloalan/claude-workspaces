"""Testes do analisador estático (seção 9 da spec)."""

from __future__ import annotations

import base64

from claude_workspaces.plugins import load_manifest
from claude_workspaces.plugins.static_analyzer import analyze_bundle


def _errs(bundle):
    return analyze_bundle(bundle, load_manifest(bundle))


def test_valid_handler_has_no_static_errors(make_bundle):
    bundle = make_bundle()
    assert _errs(bundle) == []


def test_eval_rejected(make_bundle):
    bundle = make_bundle(handler_ts='export default async () => { eval("1"); };')
    assert any("eval" in e for e in _errs(bundle))


def test_new_function_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts='export default async () => { new Function("return 1"); };'
    )
    assert any("new Function" in e for e in _errs(bundle))


def test_forbidden_node_import_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts='import fs from "node:fs";\nexport default async () => {};'
    )
    assert any("módulo proibido" in e for e in _errs(bundle))


def test_npm_package_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts='import x from "lodash";\nexport default async () => {};'
    )
    assert any("allowlist" in e for e in _errs(bundle))


def test_allowed_package_passes(make_bundle):
    bundle = make_bundle(
        handler_ts=(
            'import { HookContext } from "@claude-workspaces/api";\n'
            "export default async (ctx: HookContext) => {};"
        )
    )
    assert _errs(bundle) == []


def test_global_this_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts="export default async () => { (globalThis as any).x = 1; };"
    )
    assert any("globalThis" in e for e in _errs(bundle))


def test_set_interval_under_1000_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts="export default async () => { setInterval(() => {}, 100); };"
    )
    assert any("polling abaixo" in e for e in _errs(bundle))


def test_set_interval_above_1000_ok(make_bundle):
    bundle = make_bundle(
        handler_ts="export default async () => { setInterval(() => {}, 2000); };"
    )
    assert _errs(bundle) == []


def test_worker_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts="export default async () => { new Worker('x'); };"
    )
    assert any("Worker" in e for e in _errs(bundle))


def test_path_traversal_string_rejected(make_bundle):
    bundle = make_bundle(
        handler_ts="export default async () => { const p = '../etc/passwd'; };"
    )
    assert any("traversal" in e for e in _errs(bundle))


def test_base64_decoding_to_code_rejected(make_bundle):
    payload = base64.b64encode(
        b"function payload(){ return eval('1'); } " * 4
    ).decode("ascii")
    bundle = make_bundle(
        handler_ts=f"export default async () => {{ const x = '{payload}'; }};"
    )
    assert any("base64" in e for e in _errs(bundle))


def test_fs_usage_requires_permission(make_bundle):
    bundle = make_bundle(
        handler_ts=(
            "export default async (ctx: any) => { await ctx.fs.read('/x'); };"
        )
    )
    errs = _errs(bundle)
    assert any("ctx.fs.read" in e and "filesystem.read" in e for e in errs)


def test_declared_permission_must_be_used(make_bundle):
    bundle = make_bundle(
        overrides={
            "permissions": {
                "filesystem": {"read": ["/tmp/**"], "write": []},
                "network": {"hosts": []},
                "notifications": False,
                "workspaces": "all",
            }
        }
    )
    errs = _errs(bundle)
    assert any(
        "filesystem.read declarado" in e and "não é usado" in e for e in errs
    )


def test_notifications_permission_used(make_bundle):
    bundle = make_bundle(
        overrides={
            "permissions": {
                "filesystem": {"read": [], "write": []},
                "network": {"hosts": []},
                "notifications": True,
                "workspaces": "all",
            }
        },
        handler_ts=(
            "export default async (ctx: any) => {"
            " await ctx.ui.notify({ title: 'x', body: 'y' });"
            " };"
        ),
    )
    assert _errs(bundle) == []


def test_test_files_are_ignored(make_bundle):
    """Tests/ não rodam no host runtime — o analyzer pula."""
    bundle = make_bundle(
        extra_files={
            "tests/x.test.ts": (
                "import h from '../src/hooks/on-open';\n"
                "const bad = '../etc/passwd';\n"
                "describe('x', () => {});\n"
            )
        }
    )
    assert _errs(bundle) == []
