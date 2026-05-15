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
