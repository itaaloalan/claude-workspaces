"""Diálogo pra trocar de branch com busca incremental — necessário
quando o repo tem dezenas/centenas de branches e o submenu vira um
scroll impossível de navegar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class BranchPickerDialog(QDialog):
    """Lista filtrável de branches. `selected_branch` fica preenchido
    em `accept()` quando o usuário escolhe (Enter ou duplo-clique)."""

    def __init__(
        self,
        branches: list[str],
        current: str | None,
        repo_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Trocar branch — {repo_name}")
        self.resize(480, 420)
        self._branches = branches
        self._current = current
        self.selected_branch: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        if current:
            head = QLabel(f"<span style='color:#888'>HEAD:</span> <b>{current}</b>")
            head.setStyleSheet("font-size: 11px;")
            layout.addWidget(head)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Filtrar branches…")
        self._input.setClearButtonEnabled(True)
        self._input.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 4px 8px; color: #e6e6e6; font-size: 12px; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._input.textChanged.connect(self._apply_filter)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #1a1a1a; border: 1px solid #2c2c2c; "
            "border-radius: 4px; color: #d0d0d0; font-family: monospace; "
            "font-size: 12px; }"
            "QListWidget::item { padding: 3px 6px; }"
            "QListWidget::item:selected { background: #2a4566; color: #fff; }"
        )
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("Trocar")
        ok.setDefault(True)
        ok.clicked.connect(self._accept_selected)
        ok.setStyleSheet(
            "QPushButton { background: #3d6ea8; color: #fff; border: 0; "
            "border-radius: 4px; padding: 5px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #4a82c5; }"
        )
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

        self._populate(branches)
        self._input.setFocus()

    def _populate(self, items: list[str]) -> None:
        self._list.clear()
        for b in items:
            it = QListWidgetItem(f"● {b}" if b == self._current else f"   {b}")
            it.setData(Qt.ItemDataRole.UserRole, b)
            if b == self._current:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                it.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(it)
        # Selecionar primeira linha filtrável
        for i in range(self._list.count()):
            if self._list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable:
                self._list.setCurrentRow(i)
                break

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        if not needle:
            self._populate(self._branches)
            return
        matched = [b for b in self._branches if needle in b.lower()]
        self._populate(matched)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        self.selected_branch = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _accept_selected(self) -> None:
        it = self._list.currentItem()
        if it is None or not (it.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        self.selected_branch = it.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def eventFilter(self, obj, event):
        # Setas Up/Down no input navegam a lista — UX de palette.
        if obj is self._input and isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self._list.currentRow()
                delta = 1 if key == Qt.Key.Key_Down else -1
                new_row = row + delta
                while 0 <= new_row < self._list.count():
                    it = self._list.item(new_row)
                    if it.flags() & Qt.ItemFlag.ItemIsSelectable:
                        self._list.setCurrentRow(new_row)
                        break
                    new_row += delta
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._accept_selected()
                return True
        return super().eventFilter(obj, event)
