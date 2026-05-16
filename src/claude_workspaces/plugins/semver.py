"""SemVer estrito e parser de range mínimo (suficiente pra spec).

Suporta:
- versões `MAJOR.MINOR.PATCH` (sem pre-release nem build — a spec exige estrito)
- ranges como `">=1.0.0 <2.0.0"`, `">=1.0.0"`, `"<2.0.0"`, `"1.2.3"`
- operadores: `>=`, `<=`, `>`, `<`, `=`, `==` (sem ~ ou ^ — fora do escopo v1)

Mantemos isso aqui (sem dep externa tipo `semver`/`packaging`) para o
loader não precisar de mais nenhuma dependência além de PyYAML."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CONSTRAINT_RE = re.compile(r"^\s*(>=|<=|==|=|>|<)?\s*(\d+\.\d+\.\d+)\s*$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(s: str) -> Version:
    if not isinstance(s, str):
        raise ValueError(f"versão precisa ser string, recebi {type(s).__name__}")
    m = _VERSION_RE.match(s.strip())
    if not m:
        raise ValueError(f"versão SemVer inválida: {s!r} (esperado MAJOR.MINOR.PATCH)")
    return Version(int(m.group(1)), int(m.group(2)), int(m.group(3)))


@dataclass(frozen=True)
class _Constraint:
    op: str  # >=, <=, >, <, ==
    version: Version

    def matches(self, v: Version) -> bool:
        if self.op == ">=":
            return v >= self.version
        if self.op == "<=":
            return v <= self.version
        if self.op == ">":
            return v > self.version
        if self.op == "<":
            return v < self.version
        return v == self.version


def parse_range(s: str) -> list[_Constraint]:
    """Parse de uma string de range. Múltiplos constraints separados por espaço."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("range vazio")
    parts = s.strip().split()
    out: list[_Constraint] = []
    for p in parts:
        m = _CONSTRAINT_RE.match(p)
        if not m:
            raise ValueError(f"constraint inválido no range: {p!r}")
        op = m.group(1) or "=="
        if op == "=":
            op = "=="
        out.append(_Constraint(op, parse_version(m.group(2))))
    return out


def satisfies(version: str, range_expr: str) -> bool:
    """True se `version` satisfaz todos os constraints em `range_expr`."""
    v = parse_version(version)
    constraints = parse_range(range_expr)
    return all(c.matches(v) for c in constraints)
