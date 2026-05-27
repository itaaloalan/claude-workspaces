"""Probe da versão do backend ativo.

Compatibilidade retroativa: importar daqui ainda funciona (delega pro
backend_probe). Módulos novos devem importar de backend_probe diretamente.
"""

from .backend_probe import (  # noqa: F401
    TESTED_CLAUDE_RANGE,
    _parse_semver,
    check_compatibility,
    probe_claude_version,
    run_probe_claude,
)

TESTED_RANGE = TESTED_CLAUDE_RANGE
run_probe = run_probe_claude


def _parse_version(text: str) -> tuple[int, int, int] | None:
    return _parse_semver(text)
