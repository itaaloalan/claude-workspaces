"""Registry de plugins: install/uninstall/list/enable/disable.

Plugins ficam em `~/.config/claude-workspaces/plugins/<plugin-id>/`.
Cada install é uma cópia integral do bundle (a spec é explícita:
"sem marketplace remoto, plugins moram em disco").

Estado de habilitação por plugin: `<install>/.state/enabled.flag`
(arquivo vazio quando habilitado, ausente quando desabilitado)."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .bundle_validator import validate_layout
from .errors import RegistryError, ValidationError
from .manifest import Manifest
from .manifest_loader import load_manifest
from .static_analyzer import analyze_bundle
from .storage import PluginStorage

log = logging.getLogger(__name__)

# Versão atual do host — usada pra checar engine.claude-workspaces na install.
HOST_VERSION = "1.0.0"


def plugins_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces" / "plugins"


@dataclass(frozen=True)
class InstalledPlugin:
    """Plugin já presente no registry."""

    manifest: Manifest
    install_dir: Path
    enabled: bool

    @property
    def id(self) -> str:
        return self.manifest.id

    def storage(self) -> PluginStorage:
        return PluginStorage(self.install_dir)


class PluginRegistry:
    """Registry persistido em disco. Sem estado em memória além de caches simples."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or plugins_dir()

    @property
    def root(self) -> Path:
        return self._root

    # -------- listagem ---------------------------------------------------

    def list_installed(self) -> list[InstalledPlugin]:
        if not self._root.exists():
            return []
        out: list[InstalledPlugin] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            if not (child / "plugin.yaml").exists():
                continue
            try:
                manifest = load_manifest(child)
            except (ValidationError, Exception) as e:  # noqa: BLE001
                log.warning("Plugin instalado %s inválido: %s", child.name, e)
                continue
            out.append(
                InstalledPlugin(
                    manifest=manifest,
                    install_dir=child,
                    enabled=_is_enabled(child),
                )
            )
        return out

    def get(self, plugin_id: str) -> InstalledPlugin | None:
        for p in self.list_installed():
            if p.id == plugin_id:
                return p
        return None

    # -------- install / uninstall ---------------------------------------

    def install(self, bundle_dir: Path, *, overwrite: bool = False) -> InstalledPlugin:
        """Valida + copia o bundle pro registry.

        Etapas (ordem importa: erros baratos antes dos caros):
        1. Carrega manifesto (sintaxe + schema)
        2. Valida layout
        3. Valida análise estática dos .ts
        4. Checa engine vs HOST_VERSION
        5. Checa id duplicado
        6. Copia bundle pra plugins_dir/<id>/
        """
        manifest = load_manifest(bundle_dir)

        errs: list[str] = []
        errs.extend(validate_layout(bundle_dir, manifest))
        errs.extend(analyze_bundle(bundle_dir, manifest))

        from . import semver

        if not semver.satisfies(HOST_VERSION, manifest.engine.claude_workspaces):
            errs.append(
                f"engine.claude-workspaces = {manifest.engine.claude_workspaces!r} "
                f"não inclui host {HOST_VERSION!r}"
            )

        if errs:
            raise ValidationError(errs)

        target = self._root / manifest.id
        if target.exists():
            if not overwrite:
                raise RegistryError(
                    f"Plugin {manifest.id!r} já instalado em {target} "
                    f"(use overwrite=True pra reinstalar)"
                )
            shutil.rmtree(target)

        self._root.mkdir(parents=True, exist_ok=True)
        # Copia tudo do bundle, mas pulamos .state/ se existir no source
        # (não devia, mas defendemos).
        shutil.copytree(
            bundle_dir,
            target,
            ignore=shutil.ignore_patterns(".state", ".logs", "__pycache__"),
        )
        # Habilita por padrão
        _set_enabled(target, True)

        log.info("Plugin instalado: %s -> %s", manifest.id, target)
        return InstalledPlugin(
            manifest=manifest,
            install_dir=target,
            enabled=True,
        )

    def uninstall(self, plugin_id: str) -> None:
        target = self._root / plugin_id
        if not target.exists():
            raise RegistryError(f"Plugin {plugin_id!r} não está instalado")
        shutil.rmtree(target)
        log.info("Plugin desinstalado: %s", plugin_id)

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        target = self._root / plugin_id
        if not target.exists():
            raise RegistryError(f"Plugin {plugin_id!r} não está instalado")
        _set_enabled(target, enabled)


# ---------------- helpers ------------------------------------------------


def _enabled_flag(install_dir: Path) -> Path:
    return install_dir / ".state" / "enabled.flag"


def _is_enabled(install_dir: Path) -> bool:
    return _enabled_flag(install_dir).exists()


def _set_enabled(install_dir: Path, enabled: bool) -> None:
    flag = _enabled_flag(install_dir)
    if enabled:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(str(int(time.time())), encoding="utf-8")
    elif flag.exists():
        flag.unlink()
