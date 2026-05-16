"""Paleta de comandos de plugins (Ctrl+P).

Lista comandos declarados por plugins habilitados; Enter invoca o handler
async via `runtime.invoke_command(plugin_id, command_id)`.

Funciona como overlay leve — dialog modal sem chrome, fecha em Esc/blur."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..plugins import PluginRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Entry:
    plugin_id: str
    command_id: str
    title: str
    description: str


class PluginPaletteDialog(QDialog):
    """Modal de comandos. Aceita um `host` (PluginHost) e usa o runtime dele."""

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWindowTitle("Paleta de comandos")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(
            "QDialog { background: #1f1f1f; border: 1px solid #2c2c2c; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar comando…")
        self._search.setStyleSheet(
            "QLineEdit { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 6px 8px; color: #e6e6e6; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._search.textChanged.connect(self._refilter)
        outer.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 4px; color: #e6e6e6; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #232323; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._list.itemActivated.connect(self._invoke_selected)
        outer.addWidget(self._list, stretch=1)

        self._hint = QLabel(
            "Enter pra invocar · ↑↓ pra navegar · Esc pra fechar"
        )
        self._hint.setStyleSheet("color: #888; font-size: 11px;")
        outer.addWidget(self._hint)

        self._all_entries: list[_Entry] = []
        self._populate()
        self._refilter()

    # ----- populate ---------------------------------------------------------

    def _populate(self) -> None:
        registry = self._host.registry if self._host else PluginRegistry()
        try:
            installed = registry.list_installed()
        except Exception:
            log.exception("Falha listando plugins na paleta")
            installed = []
        out: list[_Entry] = []
        for inst in installed:
            if not inst.enabled:
                continue
            for cmd in inst.manifest.commands:
                out.append(
                    _Entry(
                        plugin_id=inst.id,
                        command_id=cmd.id,
                        title=cmd.title,
                        description=cmd.description,
                    )
                )
        self._all_entries = sorted(out, key=lambda e: e.title.lower())

    def _refilter(self) -> None:
        needle = self._search.text().strip().lower()
        self._list.clear()
        for e in self._all_entries:
            hay = f"{e.title} {e.command_id} {e.plugin_id} {e.description}".lower()
            if needle and needle not in hay:
                continue
            label = f"{e.title}\n  {e.plugin_id} · /{e.command_id}"
            if e.description:
                label += f"  ·  {e.description}"
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, e)
            self._list.addItem(li)
        if self._list.count() == 0:
            placeholder = QListWidgetItem(
                "(nenhum comando)"
                if not self._all_entries
                else "(nada bate com a busca)"
            )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
        else:
            self._list.setCurrentRow(0)

    # ----- ações ------------------------------------------------------------

    def _invoke_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, _Entry):
            return
        if self._host is None:
            log.warning("Paleta invocada sem plugin host")
            self.accept()
            return
        try:
            self._host.runtime.invoke_command(entry.plugin_id, entry.command_id)
        except Exception:
            log.exception(
                "Falha invocando %s/%s pela paleta",
                entry.plugin_id, entry.command_id,
            )
        self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Enter na busca também invoca o item selecionado
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._invoke_selected()
            return
        # ↑↓ direcionam a lista mesmo focando o search
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self._list.currentRow()
            delta = -1 if event.key() == Qt.Key.Key_Up else 1
            next_row = max(0, min(self._list.count() - 1, row + delta))
            self._list.setCurrentRow(next_row)
            return
        super().keyPressEvent(event)
