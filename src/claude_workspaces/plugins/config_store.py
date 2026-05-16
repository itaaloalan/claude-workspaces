"""Config persistida por plugin (override de defaults do manifesto).

Mora em `<install_dir>/.state/config.json`. Defaults vêm do manifesto;
qualquer chave nessse JSON sobrescreve o default. Esquema deliberadamente
permissivo: chaves desconhecidas (ex.: manifesto removeu um campo) são
ignoradas em leitura mas mantidas no arquivo, pra não destruir histórico
quando o autor faz downgrade de versão."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

# Lock por install_dir compartilhado entre instâncias: a UI lê/escreve
# pelo mesmo arquivo que o runtime, então a serialização tem que valer
# mesmo entre objetos diferentes.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(install_dir: Path) -> threading.RLock:
    key = str(install_dir.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


class PluginConfigStore:
    """Lê/escreve config persistida; faz fallback nos defaults do manifesto."""

    def __init__(self, install_dir: Path, defaults: dict[str, Any]) -> None:
        self._install_dir = install_dir
        self._state_dir = install_dir / ".state"
        self._file = self._state_dir / "config.json"
        self._defaults = dict(defaults)
        self._lock = _lock_for(install_dir)

    def _load(self) -> dict[str, Any]:
        if not self._file.exists():
            return {}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(serialized, encoding="utf-8")
        tmp.replace(self._file)

    def effective(self) -> dict[str, Any]:
        """Defaults + overrides, com overrides só pras chaves declaradas."""
        with self._lock:
            stored = self._load()
        out = dict(self._defaults)
        for k in self._defaults:
            if k in stored:
                out[k] = stored[k]
        return out

    def get(self, key: str) -> Any:
        return self.effective().get(key)

    def set(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("key precisa ser string não-vazia")
        with self._lock:
            data = self._load()
            data[key] = value
            self._write(data)

    def reset(self, key: str) -> None:
        """Remove o override; valor volta pro default do manifesto."""
        with self._lock:
            data = self._load()
            if key in data:
                del data[key]
                self._write(data)

    def is_overridden(self, key: str) -> bool:
        with self._lock:
            return key in self._load()
