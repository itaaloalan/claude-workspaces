"""Hooks como view top-level — substitui o HooksInspectorDialog quando
ativado pela ActivityBar.

Layout: toolbar (título + ações) · hint · legend · tree fill · counter.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...errors import LaunchError
from ...models import Workspace
from ...services.hooks_inspector import HookEntry, group_by_event, list_hooks
from ...services.system_open import open_in_file_manager

log = logging.getLogger(__name__)

_SCOPE_COLOR = {
    "user": "#6aa9e0",
    "project": "#5ac35a",
    "local": "#e6a23c",
}


class HooksView(QWidget):
    """View read-only de hooks do Claude (user + project + local)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        # ---------- Toolbar ----------
        toolbar = QHBoxLayout()
        title = QLabel("<h2 style='margin:0;'>🪝 Hooks</h2>")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self._open_user_btn = QPushButton("Abrir settings.json (user)")
        self._open_user_btn.clicked.connect(self._open_user_settings)
        toolbar.addWidget(self._open_user_btn)
        self._open_proj_btn = QPushButton("Abrir settings.json (projeto)")
        self._open_proj_btn.clicked.connect(self._open_project_settings)
        self._open_proj_btn.setEnabled(False)
        toolbar.addWidget(self._open_proj_btn)
        refresh_btn = QPushButton("↻ Recarregar")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        outer.addLayout(toolbar)

        hint = QLabel(
            "Hooks são comandos shell que o Claude dispara em eventos "
            "(Stop, PreToolUse, PostToolUse, etc). Aqui você vê "
            "<b>todos</b> os configurados, agrupados por evento e escopo."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b0b0b0;")
        outer.addWidget(hint)

        # Legend
        legend = QHBoxLayout()
        legend.addWidget(QLabel("<b>Escopos:</b>"))
        for scope, color in _SCOPE_COLOR.items():
            chip = QLabel(f"<span style='color:{color};'>● {scope}</span>")
            legend.addWidget(chip)
        legend.addStretch()
        outer.addLayout(legend)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Matcher / Comando", "Escopo", "Timeout"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setStyleSheet(
            "QTreeWidget { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 6px; color: #e6e6e6; }"
            "QTreeWidget::item { padding: 4px; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._tree.itemDoubleClicked.connect(self._on_open_file)
        outer.addWidget(self._tree, stretch=1)

        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        outer.addWidget(self._counter)

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self._open_proj_btn.setEnabled(bool(workspace and workspace.folders))
        self.refresh()

    def refresh(self) -> None:
        folders = self.workspace.folders if self.workspace else None
        try:
            entries = list_hooks(folders)
        except Exception:
            log.exception("Falha listando hooks")
            entries = []

        self._tree.clear()
        if not entries:
            empty = QTreeWidgetItem(["Nenhum hook configurado", "", ""])
            empty.setForeground(0, Qt.GlobalColor.gray)
            self._tree.addTopLevelItem(empty)
            self._counter.setText("0 hooks")
            return

        grouped = group_by_event(entries)
        for event, items in grouped.items():
            ev_item = QTreeWidgetItem([f"📡 {event}  ({len(items)})", "", ""])
            font: QFont = ev_item.font(0)
            font.setBold(True)
            ev_item.setFont(0, font)
            for h in items:
                child = QTreeWidgetItem([
                    self._render_command(h),
                    h.scope,
                    str(h.timeout) if h.timeout else "—",
                ])
                child.setData(0, Qt.ItemDataRole.UserRole, h)
                child.setToolTip(0, self._tooltip_for(h))
                child.setForeground(
                    1, QBrush(QColor(_SCOPE_COLOR.get(h.scope, "#c8c8c8")))
                )
                ev_item.addChild(child)
            self._tree.addTopLevelItem(ev_item)
            ev_item.setExpanded(True)

        ws_note = ""
        if self.workspace and self.workspace.folders:
            ws_note = f" · workspace: {Path(self.workspace.folders[0]).name}"
        elif not self.workspace:
            ws_note = " · selecione um workspace pra ver hooks de projeto"
        self._counter.setText(
            f"{len(entries)} hook(s) ativo(s) · duplo clique abre o arquivo{ws_note}"
        )

    @staticmethod
    def _render_command(h: HookEntry) -> str:
        prefix = f"[{h.matcher}] " if h.matcher else ""
        return f"{prefix}{h.short_command()}"

    @staticmethod
    def _tooltip_for(h: HookEntry) -> str:
        parts = [f"Arquivo: {h.source_file}", f"Evento: {h.event}"]
        if h.matcher:
            parts.append(f"Matcher: {h.matcher}")
        parts.append(f"Tipo: {h.type_}")
        if h.timeout:
            parts.append(f"Timeout: {h.timeout}s")
        parts.append("")
        parts.append("Comando completo:")
        parts.append(h.command)
        return "\n".join(parts)

    def _on_open_file(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, HookEntry):
            self._open_in_manager(str(data.source_file.parent))

    def _open_user_settings(self) -> None:
        self._open_in_manager(str(Path.home() / ".claude"))

    def _open_project_settings(self) -> None:
        if not self.workspace or not self.workspace.folders:
            return
        self._open_in_manager(str(Path(self.workspace.folders[0]) / ".claude"))

    def _open_in_manager(self, path: str) -> None:
        try:
            open_in_file_manager(path)
        except LaunchError as e:
            QMessageBox.warning(self, "Falha ao abrir", str(e))
