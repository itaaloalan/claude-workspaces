"""Análise estática AST dos `.py` do bundle (seção 9 da spec).

Usamos `ast.parse` + `ast.walk` — preciso, sem falsos positivos comuns de regex.

A spec exige análise antes do install. Aqui ficamos no lado puro (Python).
Não há sandbox kernel-level; o contrato de segurança é por API + revisão."""

from __future__ import annotations

import ast
import base64
import binascii
import re
from pathlib import Path

from .manifest import Manifest

# ---- Allowlists -----------------------------------------------------------

# Pacotes permitidos no topo de imports (qualquer dotted prefix).
_ALLOWED_TOP_PACKAGES: frozenset[str] = frozenset({
    "claude_workspaces",  # apenas `claude_workspaces.plugin_api` na prática
    "PySide6",            # pra panels
})

# Stdlib seguro (seção 9). Subpacotes (`x.y`) são aceitos via prefixo.
_ALLOWED_STDLIB: frozenset[str] = frozenset({
    "asyncio",
    "collections",
    "contextlib",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "itertools",
    "json",
    "math",
    "re",
    "string",
    "textwrap",
    "time",
    "typing",
    # parciais
    "os.path",
    "pathlib",  # PurePath OK, Path = banido por uso (não import)
})

# Importar esses módulos = rejeição imediata.
_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "os",  # OK só via "os.path" (tratado à parte)
    "sys",
    "subprocess",
    "socket",
    "urllib",
    "urllib.request",
    "requests",
    "httpx",
    "aiohttp",
    "multiprocessing",
    "threading",
    "ctypes",
    "importlib",
    "pkgutil",
    "pickle",
    "shelve",
    "marshal",
    "shutil",
    "tempfile",
    "fcntl",
    "mmap",
})

# Funções built-in proibidas (chamadas).
_FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",          # use ctx.fs.*
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
})

# Atributos dunder que dão fuga do sandbox.
_FORBIDDEN_ATTRS: frozenset[str] = frozenset({
    "__builtins__",
    "__globals__",
    "__import__",
    "__subclasses__",
    "__bases__",
    "__mro__",
    "__dict__",
})

# Heurística pra dunder via subclass-escape: `().__class__.__subclasses__()`.
# Aceitamos `__class__` isolado (legítimo p/ isinstance/typing).
_DUNDER_ESCAPE_CHAINS: tuple[tuple[str, ...], ...] = (
    ("__class__", "__subclasses__"),
    ("__class__", "__bases__"),
    ("__class__", "__mro__"),
)

_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")
_HEX_RE = re.compile(r"[0-9a-fA-F]{160,}")
_CODE_HINTS_RE = re.compile(
    r"(def\s+\w+|import\s+|class\s+\w+|lambda|exec\(|eval\(|"
    r"__import__|asyncio\.|globals\(|locals\()"
)


# ---- Entry point ---------------------------------------------------------


def analyze_bundle(bundle_dir: Path, manifest: Manifest) -> list[str]:
    """Roda todas as checagens da seção 9 nos .py do bundle.

    Retorna lista de mensagens (vazia = limpo).

    Arquivos em `tests/` são ignorados: testes rodam no ambiente do autor,
    não no host runtime."""
    errors: list[str] = []
    py_files: list[Path] = []
    for child in sorted(bundle_dir.rglob("*.py")):
        if not child.is_file():
            continue
        rel = child.relative_to(bundle_dir)
        if rel.parts and rel.parts[0] == "tests":
            continue
        py_files.append(child)

    if not py_files:
        return errors

    # Paths declarados como handlers no manifesto — só esses precisam exportar
    # `handler`. Outros .py em src/{...} são bibliotecas auxiliares.
    handler_rels: set[Path] = set()
    for h in manifest.all_handlers():
        rel = h[2:] if h.startswith("./") else h
        handler_rels.add(Path(rel))
    panel_handlers: set[Path] = {
        Path(p.handler[2:] if p.handler.startswith("./") else p.handler)
        for p in manifest.panels
    }

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: não consegui ler ({e})")
            continue
        rel = path.relative_to(bundle_dir)
        try:
            tree = ast.parse(source, filename=str(rel))
        except SyntaxError as e:
            errors.append(f"{rel}: erro de sintaxe Python — {e.msg} (linha {e.lineno})")
            continue
        errors.extend(_check_imports(tree, rel))
        errors.extend(_check_calls(tree, rel))
        errors.extend(_check_dunders(tree, rel))
        errors.extend(_check_traversal_literals(tree, rel))
        errors.extend(_check_encoded_code(tree, rel))
        if rel in handler_rels:
            errors.extend(
                _check_handler_signature(tree, rel, is_panel=rel in panel_handlers)
            )

    errors.extend(_check_permission_consistency(manifest, py_files))
    return errors


# ---- Checagens individuais ----------------------------------------------


def _is_allowed_import(module: str) -> bool:
    if module in _ALLOWED_STDLIB:
        return True
    top = module.split(".", 1)[0]
    if top in _ALLOWED_TOP_PACKAGES:
        return True
    # subpacotes de stdlib permitido (ex.: pathlib.PurePath sai como `pathlib`)
    return any(
        module == allowed or module.startswith(allowed + ".")
        for allowed in _ALLOWED_STDLIB
    )


def _check_imports(tree: ast.AST, rel: Path) -> list[str]:
    errs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                errs.extend(_classify_import(alias.name, rel))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # import relativo (`from .x import y`) — OK
                continue
            errs.extend(_classify_import(node.module or "", rel))
    return errs


def _classify_import(module: str, rel: Path) -> list[str]:
    if not module:
        return [f"{rel}: import vazio"]
    if module in _FORBIDDEN_MODULES:
        return [f"{rel}: import de módulo proibido {module!r} (seção 9.2)"]
    if module.startswith("os.") and module != "os.path":
        return [f"{rel}: import de submódulo de os proibido (apenas os.path): {module!r}"]
    if _is_allowed_import(module):
        return []
    return [
        f"{rel}: import fora do allowlist: {module!r} "
        f"(seção 9.3 — só plugin_api, stdlib segura ou PySide6)"
    ]


def _check_calls(tree: ast.AST, rel: Path) -> list[str]:
    errs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_CALLS:
                errs.append(
                    f"{rel}:{node.lineno}: chamada proibida "
                    f"{node.func.id}() (seção 9.1/9.9)"
                )
    return errs


def _attr_chain(node: ast.AST) -> list[str]:
    """Retorna a cadeia de atributos a partir de um `ast.Attribute` aninhado.

    Ex.: `a.b.c` → ['a', 'b', 'c']."""
    out: list[str] = []
    while isinstance(node, ast.Attribute):
        out.append(node.attr)
        node = node.value
    out.reverse()
    return out


def _check_dunders(tree: ast.AST, rel: Path) -> list[str]:
    errs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = _attr_chain(node)
            blocked = False
            for forbidden_chain in _DUNDER_ESCAPE_CHAINS:
                if _contains_subseq(chain, list(forbidden_chain)):
                    errs.append(
                        f"{rel}:{node.lineno}: acesso a "
                        f"{'.'.join(forbidden_chain)} proibido (seção 9.4)"
                    )
                    blocked = True
                    break
            if blocked:
                continue
            attr = chain[-1] if chain else ""
            if attr in _FORBIDDEN_ATTRS:
                errs.append(
                    f"{rel}:{node.lineno}: acesso a {attr} proibido (seção 9.4)"
                )
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_ATTRS:
            errs.append(
                f"{rel}:{node.lineno}: referência a {node.id} proibida (seção 9.4)"
            )
    return errs


def _contains_subseq(haystack: list[str], needle: list[str]) -> bool:
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i : i + len(needle)] == needle:
            return True
    return False


def _check_traversal_literals(tree: ast.AST, rel: Path) -> list[str]:
    errs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "../" in node.value or "..\\" in node.value:
                errs.append(
                    f"{rel}:{node.lineno}: string com '..' detectada — "
                    f"path traversal proibido (seção 9.8)"
                )
    return errs


def _check_encoded_code(tree: ast.AST, rel: Path) -> list[str]:
    errs: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        s = node.value
        if _BASE64_RE.fullmatch(s):
            try:
                decoded = base64.b64decode(s, validate=True).decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, binascii.Error):
                continue
            if _CODE_HINTS_RE.search(decoded):
                errs.append(
                    f"{rel}:{node.lineno}: string base64 ({len(s)} chars) "
                    f"decodifica pra algo parecido com código (seção 9.7)"
                )
                return errs
        if _HEX_RE.fullmatch(s):
            try:
                decoded = bytes.fromhex(s).decode("utf-8", errors="replace")
            except ValueError:
                continue
            if _CODE_HINTS_RE.search(decoded):
                errs.append(
                    f"{rel}:{node.lineno}: string hex ({len(s)} chars) "
                    f"decodifica pra algo parecido com código (seção 9.7)"
                )
                return errs
    return errs


def _check_handler_signature(
    tree: ast.AST, rel: Path, *, is_panel: bool
) -> list[str]:
    """Handler declarado no manifesto precisa exportar `handler`.

    Commands/hooks: `async def handler(ctx, payload?)`.
    Panels: `def handler(ctx) -> QWidget` (síncrono)."""
    handler_def: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "handler"
            ):
                handler_def = node
                break
    if handler_def is None:
        return [f"{rel}: falta `handler` exportado no top-level"]

    if is_panel:
        if isinstance(handler_def, ast.AsyncFunctionDef):
            return [
                f"{rel}: handler de panel precisa ser síncrono "
                f"(`def handler(ctx) -> QWidget`)"
            ]
        return []
    if not isinstance(handler_def, ast.AsyncFunctionDef):
        return [
            f"{rel}: handler de command/hook precisa ser "
            f"`async def handler(ctx, ...)`"
        ]
    return []


# ---- Permission consistency (seção 3.3.4-5) ------------------------------


def _walk_ctx_attribute_calls(tree: ast.AST) -> set[tuple[str, ...]]:
    """Coleta usos `ctx.x.y(...)` como (sub_api, method). Ex.: ctx.fs.read."""
    out: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            chain = _attr_chain(node.func)
            base_node = node.func
            while isinstance(base_node, ast.Attribute):
                base_node = base_node.value
            if isinstance(base_node, ast.Name) and base_node.id == "ctx":
                if len(chain) >= 2:
                    out.add(tuple(chain[:2]))
    return out


def _check_permission_consistency(
    manifest: Manifest, py_files: list[Path]
) -> list[str]:
    uses_fs_read = False
    uses_fs_write = False
    uses_http = False
    uses_notify = False

    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for sub, method in _walk_ctx_attribute_calls(tree):
            if sub == "fs":
                if method in {"read", "list"}:
                    uses_fs_read = True
                elif method == "write":
                    uses_fs_write = True
            elif sub == "http":
                uses_http = True
            elif sub == "ui" and method in {"notify", "toast"}:
                uses_notify = True

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
    return errs
