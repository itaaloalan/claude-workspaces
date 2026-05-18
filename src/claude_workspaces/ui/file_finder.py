"""Localizador de arquivos do workspace — busca fuzzy via `fd` (com
fallback puro Python) e botões pra abrir no app default (xdg-open) ou
no editor configurado."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

_MAX_RESULTS = 200
_DEBOUNCE_MS = 180


class FileFinder(QWidget):
    """Widget compacto pra localizar arquivos nas pastas do workspace.

    Emite `open_file_requested(abs_path)` quando o usuário clica em
    "Editar" ou dá double-click. "Abrir" usa xdg-open direto."""

    open_file_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._folders: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._run_search)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Localizar arquivo</b>"))
        self._input = QLineEdit()
        self._input.setPlaceholderText("Digite parte do nome do arquivo…")
        self._input.setClearButtonEnabled(True)
        self._input.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 3px 8px; color: #e6e6e6; font-size: 11px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._run_search)
        header.addWidget(self._input, stretch=1)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #1a1a1a; border: 1px solid #2c2c2c; "
            "border-radius: 4px; color: #d0d0d0; font-family: monospace; "
            "font-size: 11px; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:selected { background: #2a4566; color: #fff; }"
        )
        self._list.setMaximumHeight(180)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        btn_row.addWidget(self._status, stretch=1)

        self._open_btn = self._mk_btn("Abrir")
        self._open_btn.setToolTip("Abrir no aplicativo padrão (xdg-open)")
        self._open_btn.clicked.connect(self._on_open)
        btn_row.addWidget(self._open_btn)

        self._edit_btn = self._mk_btn("Editar", primary=True)
        self._edit_btn.setToolTip("Abrir no editor configurado")
        self._edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(self._edit_btn)
        layout.addLayout(btn_row)

        self._update_buttons()

    def _mk_btn(self, label: str, primary: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setStyleSheet(
                "QPushButton { background: #3d6ea8; color: #fff; border: 0; "
                "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }"
                "QPushButton:hover:enabled { background: #4a82c5; }"
                "QPushButton:disabled { background: #2a2a2a; color: #666; }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background: #1f1f1f; color: #e6e6e6; "
                "border: 1px solid #2c2c2c; border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
                "QPushButton:hover:enabled { border-color: #3d6ea8; color: #6aa9e0; }"
                "QPushButton:disabled { color: #666; border-color: #2a2a2a; }"
            )
        return btn

    def set_folders(self, folders: list[str]) -> None:
        self._folders = [f for f in folders if f and Path(f).is_dir()]
        self._input.clear()
        self._list.clear()
        self._status.setText("")
        self._update_buttons()

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start(_DEBOUNCE_MS)

    def _run_search(self) -> None:
        query = self._input.text().strip()
        self._list.clear()
        if not query or not self._folders:
            self._status.setText("")
            self._update_buttons()
            return
        results = _search(self._folders, query, limit=_MAX_RESULTS)
        for path, rel in results:
            item = QListWidgetItem(rel)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._list.addItem(item)
        n = len(results)
        if n == 0:
            self._status.setText("nenhum resultado")
        elif n >= _MAX_RESULTS:
            self._status.setText(f"{n}+ resultados (refine a busca)")
        else:
            self._status.setText(f"{n} resultado{'s' if n != 1 else ''}")
        if results:
            self._list.setCurrentRow(0)
        self._update_buttons()

    def _selected_path(self) -> str | None:
        item = self._list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self) -> None:
        has = self._selected_path() is not None
        self._open_btn.setEnabled(has)
        self._edit_btn.setEnabled(has)

    def _on_double_click(self, _item: QListWidgetItem) -> None:
        self._on_edit()

    def _on_edit(self) -> None:
        path = self._selected_path()
        if path:
            self.open_file_requested.emit(path)

    def _on_open(self) -> None:
        path = self._selected_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _search(folders: list[str], query: str, limit: int) -> list[tuple[str, str]]:
    """Procura arquivos cujo nome casa com `query` (case-insensitive).
    Retorna lista de (abs_path, display) — display é "pasta/relativo"
    quando há múltiplas pastas, senão só o relativo."""
    fd = shutil.which("fd")
    show_root = len(folders) > 1
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for folder in folders:
        base = Path(folder)
        try:
            paths = _fd_search(fd, base, query, limit) if fd else _py_search(base, query, limit)
        except Exception:
            log.debug("file_finder: busca falhou em %s", folder, exc_info=True)
            paths = []
        for p in paths:
            ap = str(p)
            if ap in seen:
                continue
            seen.add(ap)
            try:
                rel = str(p.relative_to(base))
            except ValueError:
                rel = ap
            display = f"{base.name}/{rel}" if show_root else rel
            out.append((ap, display))
            if len(out) >= limit:
                return out
    return out


def _fd_search(fd: str, base: Path, query: str, limit: int) -> list[Path]:
    # `fd` já ignora .gitignore e arquivos ocultos por padrão.
    cmd = [
        fd,
        "--type", "f",
        "--max-results", str(limit),
        "--ignore-case",
        query,
        str(base),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode not in (0, 1):
        return []
    return [Path(line) for line in proc.stdout.splitlines() if line]


_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
              "dist", "build", ".next", "target", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", ".tox"}


def _py_search(base: Path, query: str, limit: int) -> list[Path]:
    needle = query.lower()
    out: list[Path] = []
    for path in _walk(base):
        if needle in path.name.lower():
            out.append(path)
            if len(out) >= limit:
                break
    return out


def _walk(base: Path):
    stack = [base]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_symlink():
                continue
            if e.is_dir():
                if e.name in _SKIP_DIRS or e.name.startswith("."):
                    continue
                stack.append(e)
            elif e.is_file():
                yield e
