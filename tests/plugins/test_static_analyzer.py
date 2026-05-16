"""Testes do analisador estático AST (seção 9 da spec)."""

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
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    eval('1+1')\n"
        )
    )
    assert any("eval" in e for e in _errs(bundle))


def test_exec_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    exec('x=1')\n"
        )
    )
    assert any("exec" in e for e in _errs(bundle))


def test_compile_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    compile('x', 'x', 'exec')\n"
        )
    )
    assert any("compile" in e for e in _errs(bundle))


def test_open_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    open('/etc/passwd').read()\n"
        )
    )
    assert any("open" in e for e in _errs(bundle))


def test_subprocess_import_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import subprocess\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("subprocess" in e and "proibido" in e for e in _errs(bundle))


def test_os_import_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import os\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("os" in e and "proibido" in e for e in _errs(bundle))


def test_os_path_allowed(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import os.path\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    os.path.join('a', 'b')\n"
        )
    )
    assert _errs(bundle) == []


def test_sys_import_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import sys\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("sys" in e and "proibido" in e for e in _errs(bundle))


def test_requests_import_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import requests\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("requests" in e and "proibido" in e for e in _errs(bundle))


def test_plugin_api_allowed(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    ctx.log.info('ok')\n"
        )
    )
    assert _errs(bundle) == []


def test_stdlib_allowed(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import asyncio\n"
            "from datetime import datetime\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    await asyncio.sleep(1)\n"
        )
    )
    assert _errs(bundle) == []


def test_relative_import_allowed(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        ),
        extra_files={"src/hooks/utils.py": "x = 1\n"},
    )
    # adicionando import relativo no handler
    bundle_path = bundle / "src" / "hooks" / "on_open.py"
    src = bundle_path.read_text(encoding="utf-8")
    bundle_path.write_text("from .utils import x\n" + src, encoding="utf-8")
    assert _errs(bundle) == []


def test_third_party_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "import yaml\n"
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("allowlist" in e for e in _errs(bundle))


def test_dunder_escape_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    cls = ().__class__.__subclasses__()\n"
        )
    )
    assert any("__class__.__subclasses__" in e for e in _errs(bundle))


def test_builtins_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    b = __builtins__\n"
        )
    )
    assert any("__builtins__" in e for e in _errs(bundle))


def test_path_traversal_string_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    p = '../etc/passwd'\n"
        )
    )
    assert any("path traversal" in e for e in _errs(bundle))


def test_base64_decoding_to_code_rejected(make_bundle):
    blob = base64.b64encode(
        b"def payload(): __import__('os').system('rm')\n" * 4
    ).decode("ascii")
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            f"async def handler(ctx: HookContext, payload):\n"
            f"    blob = '{blob}'\n"
        )
    )
    assert any("base64" in e for e in _errs(bundle))


def test_fs_usage_requires_permission(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    await ctx.fs.read('/x')\n"
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
    assert any("filesystem.read declarado" in e for e in errs)


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
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "async def handler(ctx: HookContext, payload):\n"
            "    await ctx.ui.notify(title='x', body='y')\n"
        ),
    )
    assert _errs(bundle) == []


def test_test_files_are_ignored(make_bundle):
    """Tests/ não rodam no host runtime — o analyzer pula."""
    bundle = make_bundle(
        extra_files={
            "tests/test_x.py": (
                "import subprocess  # ok em tests/\n"
                "import sys\n"
                "def test_x():\n"
                "    p = '../etc/x'\n"
            ),
        },
    )
    assert _errs(bundle) == []


def test_missing_handler_export_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "# sem 'handler'\n"
            "x = 1\n"
        )
    )
    assert any("falta `handler`" in e for e in _errs(bundle))


def test_sync_handler_for_hook_rejected(make_bundle):
    bundle = make_bundle(
        handler_py=(
            "from claude_workspaces.plugin_api import HookContext\n"
            "def handler(ctx: HookContext, payload):\n"
            "    pass\n"
        )
    )
    assert any("async def handler" in e for e in _errs(bundle))


def test_syntax_error_reported(make_bundle):
    bundle = make_bundle(handler_py="async def handler(ctx, payload):\n  print(\n")
    assert any("sintaxe" in e for e in _errs(bundle))
