"""Análise estática dos `.ts` do bundle (seção 9 da spec).

Não é um parser TypeScript: usamos regex sobre o texto fonte. Falsos
positivos são tolerados para regras de segurança críticas — o autor
prefere uma rejeição justificada a um vazamento.

A spec exige análise estática **antes** do install. Aqui implementamos
o lado puro/Python; a parte "execução em sandbox sem rede" (também
mencionada na seção 9) é responsabilidade do runtime (fase 2)."""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path

from .manifest import Manifest

# ---- Padrões proibidos (todos retornam (regex, mensagem)) -----------------

# Imports nativos / módulos proibidos (cobre `import` e `require`).
_FORBIDDEN_MODULES = (
    "node:child_process",
    "node:fs",
    "node:net",
    "node:http",
    "node:https",
    "node:os",
    "node:path",
    "node:process",
    "node:vm",
    "node:worker_threads",
    "child_process",
    "fs",
    "net",
    "http",
    "https",
    "os",
    "vm",
    "worker_threads",
)

_IMPORT_RE = re.compile(
    r"""^\s*import\s+[^'"]*?from\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_BARE_IMPORT_RE = re.compile(
    r"""^\s*import\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_REQUIRE_RE = re.compile(
    r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)
_DYN_IMPORT_RE = re.compile(
    r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)

# Allowlist da seção 9: nenhum pacote npm é permitido em v1.
# Apenas imports relativos (./) e o pacote oficial do host.
_ALLOWED_PACKAGES = frozenset({"@claude-workspaces/api"})

_EVAL_RE = re.compile(r"\beval\s*\(")
_NEW_FUNCTION_RE = re.compile(r"\bnew\s+Function\s*\(")
_GLOBAL_THIS_RE = re.compile(r"\bglobalThis\b")
_WINDOW_RE = re.compile(r"\bwindow\b")
_WEBASSEMBLY_RE = re.compile(r"\bWebAssembly\b")

# Polling com intervalo abaixo de 1000ms é proibido pela seção 9.6.
# Detectamos `setInterval(..., N)` onde N é literal e < 1000.
_SET_INTERVAL_RE = re.compile(
    r"\bsetInterval\s*\([^,]+,\s*(\d+)\s*[,)]"
)

# Spawn de processo via APIs Web (Worker é tratado à parte — não é processo
# mas a spec impede WebAssembly e a sec 6 dá a regra geral: sem spawn).
_WORKER_RE = re.compile(r"\bnew\s+Worker\s*\(")

# Strings base64 grandes que decodificam pra algo parecido com código JS/TS.
_BASE64_RE = re.compile(r"['\"]([A-Za-z0-9+/]{80,}={0,2})['\"]")
_HEX_RE = re.compile(r"['\"]([0-9a-fA-F]{160,})['\"]")

# Heurística de "isto parece código" — pra reduzir falsos positivos.
_CODE_HINTS_RE = re.compile(
    r"(function\s*\(|=>|\beval\b|\bimport\b|\brequire\b|"
    r"class\s+\w+|\bconst\s+\w+\s*=|console\.|process\.)"
)

# Path traversal em strings literais (escrita indireta).
_TRAVERSAL_RE = re.compile(r"['\"][^'\"]*\.\./[^'\"]*['\"]")


def analyze_bundle(bundle_dir: Path, manifest: Manifest) -> list[str]:
    """Roda todas as checagens da seção 9 nos .ts do bundle.

    Retorna lista de mensagens (vazia = limpo).

    Arquivos em `tests/` são ignorados: testes rodam no ambiente do autor,
    não no host runtime — importar `../src/...` é o único caminho legítimo
    e regras como "sem traversal" só fazem sentido em código runtime."""
    errors: list[str] = []
    ts_files: list[Path] = []
    for child in sorted(bundle_dir.rglob("*.ts")):
        if not child.is_file():
            continue
        rel = child.relative_to(bundle_dir)
        if rel.parts and rel.parts[0] == "tests":
            continue
        ts_files.append(child)

    if not ts_files:
        # Cobertura: a validação de layout já avisa que faltam handlers.
        return errors

    for path in ts_files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: não consegui ler ({e})")
            continue
        rel = path.relative_to(bundle_dir)
        errors.extend(_check_imports(source, rel))
        errors.extend(_check_dynamic_code(source, rel))
        errors.extend(_check_global_access(source, rel))
        errors.extend(_check_polling(source, rel))
        errors.extend(_check_workers(source, rel))
        errors.extend(_check_traversal(source, rel))
        errors.extend(_check_encoded_code(source, rel))

    errors.extend(_check_permission_consistency(bundle_dir, manifest, ts_files))
    return errors


# ---- checagens individuais ----------------------------------------------


def _check_imports(source: str, rel: Path) -> list[str]:
    errs: list[str] = []
    for match in _IMPORT_RE.finditer(source):
        errs.extend(_classify_import(match.group(1), rel))
    for match in _BARE_IMPORT_RE.finditer(source):
        errs.extend(_classify_import(match.group(1), rel))
    for match in _REQUIRE_RE.finditer(source):
        errs.extend(_classify_import(match.group(1), rel, dynamic=True))
    for match in _DYN_IMPORT_RE.finditer(source):
        errs.extend(_classify_import(match.group(1), rel, dynamic=True))
    return errs


def _classify_import(module: str, rel: Path, dynamic: bool = False) -> list[str]:
    label = "import dinâmico" if dynamic else "import"
    if module in _FORBIDDEN_MODULES:
        return [f"{rel}: {label} de módulo proibido {module!r} (seção 9.2)"]
    if module.startswith("./") or module.startswith("../"):
        if "../" in module:
            return [f"{rel}: {label} relativo escapando do bundle: {module!r}"]
        return []
    if module in _ALLOWED_PACKAGES:
        return []
    return [
        f"{rel}: {label} de pacote fora do allowlist: {module!r} "
        f"(seção 9.3 — apenas relativos ou {sorted(_ALLOWED_PACKAGES)} permitidos)"
    ]


def _check_dynamic_code(source: str, rel: Path) -> list[str]:
    errs: list[str] = []
    if _EVAL_RE.search(source):
        errs.append(f"{rel}: uso de eval() proibido (seção 9.1)")
    if _NEW_FUNCTION_RE.search(source):
        errs.append(f"{rel}: uso de new Function() proibido (seção 9.1)")
    if _WEBASSEMBLY_RE.search(source):
        errs.append(f"{rel}: WebAssembly não suportado em v1 (seção 9.10)")
    return errs


def _check_global_access(source: str, rel: Path) -> list[str]:
    errs: list[str] = []
    if _GLOBAL_THIS_RE.search(source):
        errs.append(f"{rel}: acesso a globalThis proibido (seção 9.4)")
    if _WINDOW_RE.search(source):
        errs.append(f"{rel}: acesso a window proibido (seção 9.4)")
    return errs


def _check_polling(source: str, rel: Path) -> list[str]:
    errs: list[str] = []
    for match in _SET_INTERVAL_RE.finditer(source):
        try:
            interval = int(match.group(1))
        except ValueError:  # pragma: no cover — regex garante \d+
            continue
        if interval < 1000:
            errs.append(
                f"{rel}: setInterval com {interval}ms — polling abaixo de "
                f"1000ms é proibido (seção 9.6); use hooks"
            )
    return errs


def _check_workers(source: str, rel: Path) -> list[str]:
    if _WORKER_RE.search(source):
        return [f"{rel}: new Worker(...) proibido (seção 9.9 — sem spawn)"]
    return []


def _check_traversal(source: str, rel: Path) -> list[str]:
    if _TRAVERSAL_RE.search(source):
        return [
            f"{rel}: string com '../' detectada — escrita indireta via "
            f"path traversal é proibida (seção 9.8)"
        ]
    return []


def _check_encoded_code(source: str, rel: Path) -> list[str]:
    """Detecta blobs base64/hex que decodificam pra algo parecido com código."""
    errs: list[str] = []
    for match in _BASE64_RE.finditer(source):
        blob = match.group(1)
        try:
            decoded = base64.b64decode(blob, validate=True).decode("utf-8", errors="replace")
        except (ValueError, binascii.Error):
            continue
        if _CODE_HINTS_RE.search(decoded):
            errs.append(
                f"{rel}: string base64 ({len(blob)} chars) decodifica pra "
                f"algo parecido com código (seção 9.7)"
            )
            break  # uma ocorrência é suficiente — não inundamos a saída
    for match in _HEX_RE.finditer(source):
        blob = match.group(1)
        try:
            decoded = bytes.fromhex(blob).decode("utf-8", errors="replace")
        except ValueError:
            continue
        if _CODE_HINTS_RE.search(decoded):
            errs.append(
                f"{rel}: string hex ({len(blob)} chars) decodifica pra "
                f"algo parecido com código (seção 9.7)"
            )
            break
    return errs


def _check_permission_consistency(
    bundle_dir: Path, manifest: Manifest, ts_files: list[Path]
) -> list[str]:
    """Item 3.3.4-5 da spec: toda permissão usada precisa estar declarada,
    e toda permissão declarada precisa ser usada.

    Heurística: procuramos chamadas `ctx.fs.*`, `ctx.http.*`, `ctx.ui.notify`,
    `ctx.ui.toast`. Cruzamos com as permissões."""
    uses_fs_read = False
    uses_fs_write = False
    uses_http = False
    uses_notify = False
    uses_workspaces_other = False

    fs_read_re = re.compile(r"\bctx\.fs\.(read|list)\s*\(")
    fs_write_re = re.compile(r"\bctx\.fs\.write\s*\(")
    http_re = re.compile(r"\bctx\.http\.")
    notify_re = re.compile(r"\bctx\.ui\.(notify|toast)\s*\(")
    workspaces_re = re.compile(r"\bctx\.workspaces\.(list|get)\s*\(")

    for path in ts_files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if fs_read_re.search(source):
            uses_fs_read = True
        if fs_write_re.search(source):
            uses_fs_write = True
        if http_re.search(source):
            uses_http = True
        if notify_re.search(source):
            uses_notify = True
        if workspaces_re.search(source):
            uses_workspaces_other = True

    errs: list[str] = []
    perms = manifest.permissions

    if uses_fs_read and not perms.can_read_path():
        errs.append(
            "Plugin usa ctx.fs.read/list mas não declarou permissions.filesystem.read"
        )
    if uses_fs_write and not perms.can_write_path():
        errs.append(
            "Plugin usa ctx.fs.write mas não declarou permissions.filesystem.write"
        )
    if uses_http and not perms.can_use_network():
        errs.append(
            "Plugin usa ctx.http.* mas não declarou permissions.network.hosts"
        )
    if uses_notify and not perms.notifications:
        errs.append(
            "Plugin usa ctx.ui.notify/toast mas não declarou permissions.notifications"
        )

    # Permissões declaradas mas não usadas (sec 3.3.4)
    if perms.can_read_path() and not uses_fs_read:
        errs.append(
            "permissions.filesystem.read declarado mas ctx.fs.read/list não é usado"
        )
    if perms.can_write_path() and not uses_fs_write:
        errs.append(
            "permissions.filesystem.write declarado mas ctx.fs.write não é usado"
        )
    if perms.can_use_network() and not uses_http:
        errs.append("permissions.network.hosts declarado mas ctx.http.* não é usado")
    if perms.notifications and not uses_notify:
        errs.append(
            "permissions.notifications declarado mas ctx.ui.notify/toast não é usado"
        )
    # workspaces=all é difícil checar consumo — só validamos consistência se
    # uma lista finita foi declarada mas o código não acessa workspaces alheios.
    # (purposadamente sem warning aqui — muitos hooks recebem workspace via payload.)
    _ = bundle_dir, uses_workspaces_other  # silenciar linter
    return errs
