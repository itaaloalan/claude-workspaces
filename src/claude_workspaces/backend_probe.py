import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)

TESTED_CLAUDE_RANGE: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (2, 1, 0),
    (2, 1, 999),
)

TESTED_OPENCODE_RANGE: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (1, 14, 0),
    (1, 99, 999),
)


def _parse_semver(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def probe_claude_version(command: str = "claude") -> tuple[int, int, int] | None:
    if not shutil.which(command):
        log.warning("Binário '%s' não encontrado no PATH", command)
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Falha ao rodar '%s --version': %s", command, e)
        return None
    out = (result.stdout or "") + (result.stderr or "")
    version = _parse_semver(out)
    if version is None:
        log.warning("Não consegui parsear versão de: %r", out.strip())
        return None
    return version


def probe_opencode_version(command: str = "opencode") -> tuple[int, int, int] | None:
    if not shutil.which(command):
        log.warning("Binário '%s' não encontrado no PATH", command)
        return None
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Falha ao rodar '%s --version': %s", command, e)
        return None
    out = (result.stdout or "") + (result.stderr or "")
    version = _parse_semver(out)
    if version is None:
        log.warning("Não consegui parsear versão do opencode de: %r", out.strip())
        return None
    return version


def check_compatibility(
    version: tuple[int, int, int] | None,
    tested_range: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
    name: str = "CLI",
) -> bool:
    """Loga compatibilidade e devolve True se versão estiver no range testado.
    `name` é o label do CLI (ex: 'Claude Code', 'opencode'). Compatibilidade
    retroativa: chamar com (version, range) ainda funciona porque range é o
    segundo positional."""
    if version is None:
        return False
    if tested_range is None:
        return True
    lo, hi = tested_range

    def fmt(v: tuple[int, int, int]) -> str:
        return ".".join(str(x) for x in v)

    if lo <= version <= hi:
        log.info("%s %s detectado (range testado: %s–%s)", name, fmt(version), fmt(lo), fmt(hi))
        return True
    if version < lo:
        log.warning(
            "%s %s é mais ANTIGO que o range testado (%s–%s).",
            name, fmt(version), fmt(lo), fmt(hi),
        )
    else:
        log.warning(
            "%s %s é mais NOVO que o range testado (%s–%s).",
            name, fmt(version), fmt(lo), fmt(hi),
        )
    return False


def run_probe_claude(command: str = "claude") -> tuple[int, int, int] | None:
    version = probe_claude_version(command)
    check_compatibility(version, TESTED_CLAUDE_RANGE, name="Claude Code")
    return version


def run_probe_opencode(command: str = "opencode") -> tuple[int, int, int] | None:
    version = probe_opencode_version(command)
    check_compatibility(version, TESTED_OPENCODE_RANGE, name="opencode")
    return version


def run_probe(backend: str = "claude") -> None:
    if backend == "opencode":
        run_probe_opencode()
    else:
        run_probe_claude()
