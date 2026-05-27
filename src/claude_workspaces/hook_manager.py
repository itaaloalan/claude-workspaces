"""Gerencia o hook Stop do backend ativo (Claude Code ou opencode),
preservando outros hooks que o usuário tenha configurado."""

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

HOOK_FILENAME = "notify-hook.py"


def claude_settings_file() -> Path:
    return Path.home() / ".claude" / "settings.json"


def opencode_config_file() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.jsonc"


def app_data_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces"


def installed_hook_script() -> Path:
    return app_data_dir() / HOOK_FILENAME


def _package_hook_script() -> Path:
    """Encontra o packaging/notify-hook.py no checkout do source."""
    here = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = here / "packaging" / HOOK_FILENAME
        if candidate.exists():
            return candidate
        if here == here.parent:
            break
        here = here.parent
    raise FileNotFoundError(
        f"Não encontrei packaging/{HOOK_FILENAME} no source checkout"
    )


def _hook_command_matches(cmd: str) -> bool:
    return cmd.endswith(HOOK_FILENAME)


def is_hook_installed(backend: str = "claude") -> bool:
    if backend == "opencode":
        return _is_opencode_hook_installed()
    return _is_claude_hook_installed()


def _is_claude_hook_installed() -> bool:
    settings_path = claude_settings_file()
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    stop_hooks = data.get("hooks", {}).get("Stop", [])
    if not isinstance(stop_hooks, list):
        return False
    for entry in stop_hooks:
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []):
            if isinstance(h, dict) and _hook_command_matches(h.get("command", "")):
                return True
    return False


def _is_opencode_hook_installed() -> bool:
    """opencode usa opencode.jsonc pra hooks (ainda não implementado)."""
    # TODO: implementar quando opencode suportar hooks Stop
    return False


def refresh_installed_hook(backend: str = "claude") -> bool:
    if backend == "opencode":
        return False  # TODO: opencode hook support
    if not is_hook_installed(backend):
        return False
    try:
        src = _package_hook_script()
    except FileNotFoundError:
        return False
    dst = installed_hook_script()
    try:
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            return False
    except OSError:
        pass
    try:
        shutil.copy(src, dst)
        dst.chmod(0o755)
        log.info("Hook atualizado em %s", dst)
        return True
    except OSError:
        log.warning("Falha ao atualizar hook em %s", dst, exc_info=True)
        return False


def install_hook(backend: str = "claude") -> Path:
    """Copia o script pra ~/.config/claude-workspaces/ e adiciona o hook
    Stop no config do backend ativo."""
    app_data_dir().mkdir(parents=True, exist_ok=True)
    src = _package_hook_script()
    dst = installed_hook_script()
    shutil.copy(src, dst)
    dst.chmod(0o755)
    log.info("Hook copiado pra %s", dst)

    if backend == "opencode":
        log.warning("opencode hook support not yet implemented")
        return dst

    settings_path = claude_settings_file()
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("settings.json inválido, recriando")
            data = {}
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])
    if not isinstance(stop_hooks, list):
        stop_hooks = []
        hooks["Stop"] = stop_hooks

    already_installed = False
    for entry in stop_hooks:
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []):
            if isinstance(h, dict) and _hook_command_matches(h.get("command", "")):
                already_installed = True
                break
        if already_installed:
            break

    if not already_installed:
        stop_hooks.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": str(dst)}],
            }
        )

    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Hook registrado em %s", settings_path)
    return dst


def uninstall_hook(backend: str = "claude") -> None:
    if backend == "opencode":
        log.warning("opencode hook support not yet implemented")
        return

    settings_path = claude_settings_file()
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

        hooks = data.get("hooks")
        if isinstance(hooks, dict):
            stop_hooks = hooks.get("Stop")
            if isinstance(stop_hooks, list):
                new_stop = []
                for entry in stop_hooks:
                    if not isinstance(entry, dict):
                        new_stop.append(entry)
                        continue
                    inner = entry.get("hooks", [])
                    new_inner = [
                        h
                        for h in inner
                        if not (
                            isinstance(h, dict)
                            and _hook_command_matches(h.get("command", ""))
                        )
                    ]
                    if new_inner:
                        entry["hooks"] = new_inner
                        new_stop.append(entry)
                if new_stop:
                    hooks["Stop"] = new_stop
                else:
                    hooks.pop("Stop", None)
                if not hooks:
                    data.pop("hooks", None)

        settings_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Hook removido de %s", settings_path)

    installed = installed_hook_script()
    if installed.exists():
        try:
            installed.unlink()
            log.info("Script de hook removido: %s", installed)
        except OSError:
            log.warning("Falha ao remover %s", installed)
