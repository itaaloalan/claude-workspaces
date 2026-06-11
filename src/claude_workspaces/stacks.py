import time
from pathlib import Path

STACK_INDICATORS: dict[str, list[str]] = {
    "java": [
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
    ],
    "web": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
}

STACK_GLOBS: dict[str, list[str]] = {
    "csharp": ["*.csproj", "*.sln", "*.fsproj"],
}

STACK_LABEL: dict[str, str] = {
    "java": "Java",
    "web": "Web",
    "python": "Python",
    "csharp": "C#",
}

STACK_TO_IDE: dict[str, str] = {
    "java": "intellij",
    "web": "webstorm",
    "python": "pycharm",
    "csharp": "rider",
}


def detect_stacks(folders: list[str]) -> set[str]:
    found: set[str] = set()
    for folder in folders:
        p = Path(folder)
        if not p.is_dir():
            continue
        for stack, names in STACK_INDICATORS.items():
            if any((p / name).exists() for name in names):
                found.add(stack)
        for stack, patterns in STACK_GLOBS.items():
            if any(next(p.glob(pattern), None) is not None for pattern in patterns):
                found.add(stack)
    return found


# Cache TTL por tuple(folders): detect_stacks faz IO de filesystem
# (exists/glob) e é chamado a cada seleção de workspace (sidebar + status
# bar). Pastas raramente mudam de stack; 30s mantém responsivo sem reler.
_STACKS_TTL_S = 30.0
_stacks_cache: dict[tuple[str, ...], tuple[float, set[str]]] = {}


def detect_stacks_cached(folders: list[str]) -> set[str]:
    key = tuple(folders)
    now = time.monotonic()
    hit = _stacks_cache.get(key)
    if hit is not None and (now - hit[0]) < _STACKS_TTL_S:
        return set(hit[1])
    result = detect_stacks(folders)
    # Poda expiradas no insert — workspaces editados/removidos mudam a
    # tuple-chave e a entrada antiga ficaria órfã pra sempre.
    for k in [k for k, v in _stacks_cache.items() if (now - v[0]) >= _STACKS_TTL_S]:
        _stacks_cache.pop(k, None)
    _stacks_cache[key] = (now, set(result))
    return result
