"""Helpers compartilhados pelos testes de plugins.

`make_bundle(tmp_path, overrides=None, files=None)` constrói um bundle
mínimo válido in-place pra testes parametrizados — evita centenas de
linhas de boilerplate em cada teste."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


VALID_MANIFEST: dict[str, Any] = {
    "id": "com.exemplo.plug",
    "name": "Plug",
    "version": "0.1.0",
    "author": "Italo",
    "description": "Plugin de teste",
    "license": "MIT",
    "engine": {"claude-workspaces": ">=1.0.0 <2.0.0"},
    "extensions": {
        "hooks": [
            {"event": "workspace.opened", "handler": "./src/hooks/on_open.py"}
        ]
    },
    "permissions": {
        "filesystem": {"read": [], "write": []},
        "network": {"hosts": []},
        "notifications": False,
        "workspaces": "all",
    },
}

VALID_HANDLER_PY = """\
from claude_workspaces.plugin_api import HookContext


async def handler(ctx: HookContext, payload) -> None:
    ctx.log.info("hello")
"""

VALID_README = (
    "# Plug\n\nPlugin de exemplo pros testes do registry. " * 5
)


@pytest.fixture
def make_bundle(tmp_path: Path):
    """Fixture: cria um bundle mínimo válido em `tmp_path/<nome>/`.

    Uso:
        bundle = make_bundle()                                  # nome auto
        bundle = make_bundle(overrides={"id": "...", "name": "..."})
        bundle = make_bundle(extra_files={"src/hooks/extra.py": "..."})
    """
    counter = {"n": 0}

    def factory(
        *,
        overrides: dict[str, Any] | None = None,
        readme: str = VALID_README,
        handler_py: str = VALID_HANDLER_PY,
        extra_files: dict[str, str] | None = None,
        skip_default_handler: bool = False,
        bundle_name: str | None = None,
    ) -> Path:
        counter["n"] += 1
        name = bundle_name or f"bundle-{counter['n']}"
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)

        manifest = _deep_merge(VALID_MANIFEST, overrides or {})
        (root / "plugin.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (root / "README.md").write_text(readme, encoding="utf-8")

        if not skip_default_handler:
            (root / "src" / "hooks").mkdir(parents=True, exist_ok=True)
            (root / "src" / "__init__.py").write_text("", encoding="utf-8")
            (root / "src" / "hooks" / "__init__.py").write_text("", encoding="utf-8")
            (root / "src" / "hooks" / "on_open.py").write_text(
                handler_py, encoding="utf-8"
            )

        if extra_files:
            for rel, content in extra_files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        return root

    return factory


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    """Isola o registry num diretório temporário (não toca em ~/.config)."""
    root = tmp_path / "registry"
    root.mkdir()
    return root
