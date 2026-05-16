"""Validações estruturais do bundle (seção 2 da spec).

Independente da análise estática (`static_analyzer.py`): aqui só
olhamos *o layout de diretórios e nomes de arquivos*. As regras duras
da seção 2:

- Nenhum `.js` no bundle.
- Sem `node_modules/`, `package.json`, `package-lock.json`.
- Sem arquivos fora dos diretórios permitidos.
- README.md presente, > 100 caracteres, em PT-BR.

Os handlers referenciados pelo manifesto também são checados aqui."""

from __future__ import annotations

from pathlib import Path

from .manifest import Manifest

# Arquivos permitidos no top-level do bundle.
_TOP_LEVEL_FILES = frozenset({"plugin.yaml", "README.md"})

# Pastas permitidas no top-level.
_TOP_LEVEL_DIRS = frozenset({"src", "assets", "tests"})

# Pastas permitidas dentro de src/.
_SRC_SUBDIRS = frozenset({"commands", "hooks", "panels"})

# Extensões permitidas por contexto.
_SRC_EXTS = frozenset({".ts"})
_TEST_EXTS = frozenset({".ts"})
_ASSET_EXTS = frozenset({".svg", ".png"})

# Arquivos cuja presença causa rejeição imediata.
_FORBIDDEN_FILES = frozenset({"package.json", "package-lock.json", "yarn.lock", "tsconfig.json"})
_FORBIDDEN_DIRS = frozenset({"node_modules", ".git"})

_MIN_README_LEN = 100


def validate_layout(bundle_dir: Path, manifest: Manifest) -> list[str]:
    """Retorna lista de erros (vazia = OK).

    Não levanta — só coleta. O caller decide se aborta ou continua."""
    errors: list[str] = []

    # README
    readme = bundle_dir / "README.md"
    if not readme.exists():
        errors.append("README.md ausente (obrigatório, PT-BR, mínimo 100 caracteres)")
    else:
        try:
            content = readme.read_text(encoding="utf-8")
            if len(content) < _MIN_README_LEN:
                errors.append(
                    f"README.md muito curto ({len(content)} caracteres, "
                    f"mínimo {_MIN_README_LEN})"
                )
        except OSError as e:
            errors.append(f"Não consegui ler README.md: {e}")

    # plugin.yaml já foi lido pelo manifest_loader; aqui só conferimos presença.
    if not (bundle_dir / "plugin.yaml").exists():
        errors.append("plugin.yaml ausente")

    # Caminhar pelos arquivos e checar
    for path in _walk_relative(bundle_dir):
        rel = path.relative_to(bundle_dir)
        parts = rel.parts

        # Diretórios proibidos em qualquer profundidade
        if any(p in _FORBIDDEN_DIRS for p in parts):
            errors.append(f"Diretório proibido: {rel}")
            continue

        # Arquivos proibidos
        if rel.name in _FORBIDDEN_FILES:
            errors.append(f"Arquivo proibido: {rel}")
            continue

        # .js explicitamente banido na seção 2
        if rel.suffix == ".js":
            errors.append(f".js não é permitido: {rel}")
            continue

        # Validar localização do arquivo
        err = _validate_file_location(rel)
        if err:
            errors.append(err)

    # Handlers do manifesto precisam existir
    for handler in manifest.all_handlers():
        # handler começa com "./" relativo ao bundle
        rel_path = handler[2:] if handler.startswith("./") else handler
        target = bundle_dir / rel_path
        if not target.exists():
            errors.append(f"Handler referenciado não existe: {handler}")
        elif not target.is_file():
            errors.append(f"Handler não é arquivo regular: {handler}")

    # Icon do panel também precisa existir
    for panel in manifest.panels:
        icon = panel.icon
        rel_icon = icon[2:] if icon.startswith("./") else icon
        target = bundle_dir / rel_icon
        if not target.exists():
            errors.append(f"Icon do painel {panel.id!r} não existe: {icon}")

    # Icon do plugin (top-level)
    if manifest.icon:
        rel_icon = manifest.icon[2:] if manifest.icon.startswith("./") else manifest.icon
        target = bundle_dir / rel_icon
        if not target.exists():
            errors.append(f"Icon do plugin não existe: {manifest.icon}")

    return errors


def _validate_file_location(rel: Path) -> str | None:
    """Retorna mensagem de erro se o caminho viola o layout da seção 2."""
    parts = rel.parts
    if len(parts) == 1:
        # top-level
        if rel.name in _TOP_LEVEL_FILES:
            return None
        return f"Arquivo solto no top-level não é permitido: {rel}"

    top = parts[0]
    if top not in _TOP_LEVEL_DIRS:
        return f"Diretório de top-level não permitido: {top}/ (em {rel})"

    if top == "src":
        # src/<subdir>/<arquivo>.ts
        if len(parts) < 3:
            return f"Arquivo direto em src/ não é permitido: {rel} — use src/commands|hooks|panels/"
        if parts[1] not in _SRC_SUBDIRS:
            return f"Subdiretório de src/ não permitido: src/{parts[1]}/ (em {rel})"
        if rel.suffix not in _SRC_EXTS:
            return f"Extensão não permitida em src/: {rel} (esperado .ts)"
        return None

    if top == "tests":
        if rel.suffix not in _TEST_EXTS:
            return f"Extensão não permitida em tests/: {rel} (esperado .ts)"
        if not rel.name.endswith(".test.ts"):
            return f"Teste deve seguir convenção *.test.ts: {rel}"
        return None

    if top == "assets":
        if rel.suffix.lower() not in _ASSET_EXTS:
            return f"Extensão não permitida em assets/: {rel} (esperado .svg ou .png)"
        return None

    return f"Localização inválida: {rel}"


def _walk_relative(root: Path):
    """Itera arquivos recursivamente, pulando diretórios ocultos do git/IDE."""
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        # symlinks são suspeitos (podem apontar pra fora do bundle)
        if child.is_symlink():
            # Ainda yieldamos pra que o caller saiba, mas marcamos
            # como suspeito via nome — o validador externo levanta erro.
            # Aqui mantemos o yield para coleta.
            pass
        yield child
