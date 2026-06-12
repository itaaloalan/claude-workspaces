"""Detecção do "ícone real" de um projeto pra usar no card do workspace.

Varre a(s) pasta(s) do projeto atrás dos arquivos de ícone/logo mais
prováveis (favicon, logo, app icon) nos lugares convencionais de cada
stack (web `public/`, Android `res/mipmap`, .NET `*.ico`, etc) e devolve
os candidatos existentes, do mais provável pro menos.

Mantém a varredura barata: só checa caminhos/globs conhecidos em pastas
rasas — nunca faz walk recursivo da árvore inteira (node_modules!).
"""

from __future__ import annotations

from pathlib import Path

# Extensões de imagem que conseguimos renderizar no QLabel (Qt + QtSvg).
IMAGE_EXTS = {".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# Arquivos exatos no raiz do projeto, em ordem de preferência.
_ROOT_NAMES = (
    "favicon.ico",
    "favicon.png",
    "favicon.svg",
    "logo.svg",
    "logo.png",
    "icon.svg",
    "icon.png",
    "app-icon.png",
    "appicon.png",
)

# Subpastas rasas + globs onde costuma viver o ícone, por stack. Cada
# entrada é (subdir, glob). Resolvidas relativas a cada pasta do workspace.
_GLOB_DIRS = (
    ("public", "favicon.*"),
    ("public", "logo*.*"),
    ("public", "icon*.*"),
    ("public", "apple-touch-icon*.*"),
    ("static", "favicon.*"),
    ("static", "logo*.*"),
    ("assets", "icon*.*"),
    ("assets", "logo*.*"),
    ("src/assets", "icon*.*"),
    ("src/assets", "logo*.*"),
    ("resources", "icon*.*"),
    ("www", "favicon.*"),
    # Expo / React Native
    ("assets", "*icon*.png"),
    # Android
    ("app/src/main/res/mipmap-xxxhdpi", "ic_launcher*.png"),
    ("app/src/main/res/mipmap-xxhdpi", "ic_launcher*.png"),
    # iOS / generic
    ("Assets.xcassets/AppIcon.appiconset", "*.png"),
)


def _ordered_unique(paths: list[Path]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        try:
            rp = str(p.resolve())
        except OSError:
            rp = str(p)
        if rp not in seen and p.is_file():
            seen.add(rp)
            out.append(str(p))
    return out


def detect_project_icons(folders: str | list[str], limit: int = 12) -> list[str]:
    """Candidatos a "ícone do projeto" nas `folders`, do mais provável ao
    menos. Aceita uma pasta única ou uma lista (workspaces multi-repo).

    Determinístico: nomes exatos do raiz primeiro, depois os globs por
    stack na ordem de `_GLOB_DIRS`, dedup preservando a ordem. Limitado a
    `limit` pra não explodir o menu."""
    if isinstance(folders, str):
        folders = [folders]
    hits: list[Path] = []
    for folder in folders:
        if not folder:
            continue
        root = Path(folder)
        if not root.is_dir():
            continue
        for name in _ROOT_NAMES:
            hits.append(root / name)
        for subdir, glob in _GLOB_DIRS:
            base = root / subdir
            if not base.is_dir():
                continue
            try:
                matches = sorted(
                    p for p in base.glob(glob)
                    if p.suffix.lower() in IMAGE_EXTS
                )
            except OSError:
                continue
            hits.extend(matches)
    return _ordered_unique(hits)[:limit]


def is_image_file(path: str) -> bool:
    """True se `path` existe e tem extensão de imagem suportada."""
    if not path:
        return False
    p = Path(path)
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS
