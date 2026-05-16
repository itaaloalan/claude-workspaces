"""Storage isolado por plugin (seção 5.5 da spec).

Dados persistidos em `<plugin_install_dir>/.state/store.json` com cota
de 10 MB. Toda operação é serializada por um lock por-plugin para evitar
corrida entre handlers paralelos do mesmo plugin."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .errors import StorageQuotaError

_QUOTA_BYTES = 10 * 1024 * 1024  # 10 MB

# Locks compartilhados — um por install_dir. Usamos um dicionário fraco-equivalente:
# como os install dirs são poucos (handful de plugins instalados), aceitamos o vazamento
# inofensivo de entradas até o app reiniciar.
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


class PluginStorage:
    """API correspondente à seção 5.5 (`ctx.storage.*`).

    Cada instância pertence a um plugin instalado. Persistência é em JSON
    para simplicidade (legível, diff-friendly em git). Para volumes maiores
    o autor pode usar `ctx.fs.write` com permissão declarada."""

    def __init__(self, install_dir: Path) -> None:
        self._install_dir = install_dir
        self._state_dir = install_dir / ".state"
        self._file = self._state_dir / "store.json"
        self._lock = _lock_for(install_dir)

    def _load(self) -> dict[str, Any]:
        if not self._file.exists():
            return {}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Storage corrompido: tratamos como vazio (handler nunca deve crashar
            # por causa do storage; o autor pode olhar logs).
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write(self, payload: dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(serialized.encode("utf-8")) > _QUOTA_BYTES:
            raise StorageQuotaError(
                f"Storage do plugin excederia 10 MB (atual proposto: "
                f"{len(serialized)} bytes)"
            )
        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(serialized, encoding="utf-8")
        tmp.replace(self._file)

    # -------------- API pública ------------------------------------------

    def get(self, key: str) -> Any | None:
        with self._lock:
            data = self._load()
            return data.get(key)

    def set(self, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("key precisa ser string não-vazia")
        with self._lock:
            data = self._load()
            data[key] = value
            self._write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if key in data:
                del data[key]
                self._write(data)

    def clear(self) -> None:
        with self._lock:
            if self._file.exists():
                self._file.unlink()

    def size_bytes(self) -> int:
        with self._lock:
            if not self._file.exists():
                return 0
            return self._file.stat().st_size
