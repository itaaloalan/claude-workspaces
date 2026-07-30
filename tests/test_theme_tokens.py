"""Ratchet de cores hardcoded fora do theme.py.

A paleta vive em ui/theme.py; hex inline em outros arquivos é dívida
(deveria consumir tokens). Este teste NÃO exige zero — só impede o
número de SUBIR: se você adicionar hex novo fora do theme.py, ou troca
por token, ou (se for cor semanticamente nova) adiciona o token em
theme.py e atualiza a baseline AQUI com o novo total menor/igual.
"""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "claude_workspaces"

# Baseline em 2026-07-30 (pós-Fase 3 do redesign Orca). Só pode DESCER.
BASELINE_OUTSIDE_THEME = 970

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def _count_hexes_outside_theme() -> tuple[int, dict[str, int]]:
    per_file: dict[str, int] = {}
    total = 0
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "theme.py":
            continue
        n = len(_HEX_RE.findall(path.read_text(encoding="utf-8")))
        if n:
            per_file[str(path.relative_to(SRC))] = n
            total += n
    return total, per_file


def test_hexes_fora_do_theme_nao_sobem():
    total, per_file = _count_hexes_outside_theme()
    top = sorted(per_file.items(), key=lambda kv: -kv[1])[:8]
    assert total <= BASELINE_OUTSIDE_THEME, (
        f"{total} hexes fora do theme.py (baseline {BASELINE_OUTSIDE_THEME}). "
        f"Use tokens de ui/theme.py em vez de hex inline. Top ofensores: {top}"
    )
