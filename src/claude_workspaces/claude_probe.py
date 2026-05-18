"""Probe da versão do Claude Code no startup.

Várias integrações nossas dependem de detalhes não-documentados do Claude
Code (formato dos JSONLs em ~/.claude/projects/, escape de Shift+Tab,
slash commands, copy do TUI usado pra detecção de estado). Quando o
Anthropic muda algo nesses pontos a gente quebra.

Esse probe roda `claude --version` no startup, parseia e compara com um
range testado. Não bloqueia nada — só loga (warning quando fora do range
testado, info quando dentro). Útil pra explicar bugs de "tava funcionando
ontem" depois de um auto-update do Claude Code.

Quando subir/baixar o range testado:
- atualize `TESTED_CLAUDE_RANGE`
- documente no CHANGELOG.md
- se schema do JSONL ou copy do TUI mudou, ajuste `claude_sessions.py`,
  `claude_activity.py`, `usage_telemetry.py` antes de bumpar o range
"""

import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)


# Range de versões do Claude Code testadas com este app. Atualize após
# rodar uma sessão real numa versão nova e confirmar que:
# - tokens/custo aparecem certo no menu de contexto
# - títulos de sessão resolvem
# - estados (working/awaiting/idle) batem com o TUI
# - Shift+Tab e /model/effort funcionam
TESTED_CLAUDE_RANGE: tuple[tuple[int, int, int], tuple[int, int, int]] = (
    (2, 1, 0),
    (2, 1, 999),
)


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Extrai (major, minor, patch) de uma string tipo '2.1.143 (Claude Code)'."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def probe_claude_version(command: str = "claude") -> tuple[int, int, int] | None:
    """Roda `<command> --version` e devolve (major, minor, patch).
    Devolve None se o binário não estiver no PATH, falhar ao executar
    ou produzir output inesperado."""
    if not shutil.which(command):
        log.warning("Binário '%s' não encontrado no PATH — integrações com Claude Code não vão funcionar", command)
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
    version = _parse_version(out)
    if version is None:
        log.warning("Não consegui parsear versão do Claude Code de: %r", out.strip())
        return None
    return version


def check_compatibility(
    version: tuple[int, int, int] | None,
    tested_range: tuple[tuple[int, int, int], tuple[int, int, int]] = TESTED_CLAUDE_RANGE,
) -> bool:
    """Loga compatibilidade e devolve True se versão estiver no range testado."""
    if version is None:
        return False
    lo, hi = tested_range

    def fmt(v: tuple[int, int, int]) -> str:
        return ".".join(str(x) for x in v)

    if lo <= version <= hi:
        log.info("Claude Code %s detectado (range testado: %s–%s)", fmt(version), fmt(lo), fmt(hi))
        return True
    if version < lo:
        log.warning(
            "Claude Code %s é mais ANTIGO que o range testado (%s–%s). "
            "Recursos como /model, /effort, Shift+Tab e parsing de JSONL podem "
            "não funcionar. Considere atualizar.",
            fmt(version), fmt(lo), fmt(hi),
        )
    else:
        log.warning(
            "Claude Code %s é mais NOVO que o range testado (%s–%s). "
            "Integrações podem quebrar se o Anthropic mudou: schema dos JSONLs "
            "em ~/.claude/projects/, copy do TUI usado pra detectar estado, "
            "ou os slash commands /model e /effort. Se algo parecer errado, "
            "verifique o changelog do Claude Code.",
            fmt(version), fmt(lo), fmt(hi),
        )
    return False


def run_probe(command: str = "claude") -> tuple[int, int, int] | None:
    """Entry point — roda probe + check num único passo. Não bloqueia."""
    version = probe_claude_version(command)
    check_compatibility(version)
    return version
