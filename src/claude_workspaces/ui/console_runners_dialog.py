"""ConsoleRunnersDialog — visão geral dos runners console-scoped.

Cópias console-scoped ("⬇ Subir stack") se acumulam em `workspace.runners`,
inclusive de consoles já fechados (órfãos). Este dialog lista quantos
consoles/sessões têm runners e permite remover por grupo ou limpar os
órfãos de uma vez. A remoção real é injetada (`on_remove(sid)`) — quem
para processos vivos e persiste é a main_window.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme

_REMOVE_BTN_QSS = (
    "QPushButton { background: transparent; color: #9aa0a6; "
    "border: 1px solid #2c2c2c; border-radius: 4px; padding: 2px 8px; "
    "font-size: 11px; }"
    "QPushButton:hover { color: #e06c75; border-color: #e06c75; }"
)


class ConsoleRunnersDialog(QDialog):
    """Lista grupos de runners por console e remove via callback.

    `groups_provider() -> list[dict]` com chaves: sid, label, open (bool),
    runners (list[str] já formatados). `on_remove(sid)` remove o grupo
    (sem confirmar — a confirmação é daqui).
    """

    def __init__(
        self,
        groups_provider: Callable[[], list[dict]],
        on_remove: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._groups_provider = groups_provider
        self._on_remove = on_remove
        self.setWindowTitle("Runners de consoles")
        self.setMinimumSize(560, 360)

        outer = QVBoxLayout(self)

        self._summary = QLabel("")
        self._summary.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; font-weight: 600;"
        )
        outer.addWidget(self._summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 4, 0, 4)
        self._rows.setSpacing(6)
        scroll.setWidget(self._rows_host)
        outer.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        self._clean_btn = QPushButton("🗑 Remover de consoles fechados")
        self._clean_btn.setToolTip(
            "Remove os runners de todos os consoles que não estão mais "
            "abertos (órfãos)."
        )
        self._clean_btn.clicked.connect(self._remove_orphans)
        footer.addWidget(self._clean_btn)
        footer.addStretch(1)
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        self._render()

    # ---- render ------------------------------------------------------------

    def _render(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        groups = self._groups_provider()
        total_runners = sum(len(g.get("runners", [])) for g in groups)
        n = len(groups)
        self._summary.setText(
            "Nenhum console com runners."
            if not groups
            else f"{n} console{'s' if n != 1 else ''} com runners · "
                 f"{total_runners} runner{'s' if total_runners != 1 else ''}"
        )
        self._clean_btn.setEnabled(any(not g.get("open") for g in groups))
        for g in groups:
            self._rows.addWidget(self._make_row(g))
        self._rows.addStretch(1)

    def _make_row(self, group: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background: #161616; border: 1px solid #242424; "
            "border-radius: 6px; }"
            "QLabel { background: transparent; border: 0; }"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)

        is_open = bool(group.get("open"))
        dot = QLabel("🟢" if is_open else "⚪")
        dot.setToolTip("Console aberto" if is_open else "Console fechado (órfão)")
        h.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(group.get("label") or "(console)")
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;"
        )
        title.setWordWrap(True)
        col.addWidget(title)
        runners = group.get("runners", [])
        detail = QLabel(
            f"{len(runners)} runner{'s' if len(runners) != 1 else ''}: "
            + ", ".join(runners)
        )
        detail.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        detail.setWordWrap(True)
        col.addWidget(detail)
        h.addLayout(col, stretch=1)

        rm = QPushButton("🗑 Remover")
        rm.setStyleSheet(_REMOVE_BTN_QSS)
        rm.clicked.connect(
            lambda _c=False, g=group: self._confirm_remove(g)
        )
        h.addWidget(rm, 0, Qt.AlignmentFlag.AlignTop)
        return row

    # ---- ações -------------------------------------------------------------

    def _confirm_remove(self, group: dict) -> None:
        runners = group.get("runners", [])
        extra = (
            "\n\nO console está ABERTO — runners em execução serão parados."
            if group.get("open") else ""
        )
        if (
            QMessageBox.question(
                self,
                "Remover runners do console",
                f"Remover os {len(runners)} runner(s) de:\n"
                f"{group.get('label') or group.get('sid')}\n\n"
                + ", ".join(runners) + extra,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._on_remove(group["sid"])
        self._render()

    def _remove_orphans(self) -> None:
        orphans = [g for g in self._groups_provider() if not g.get("open")]
        if not orphans:
            return
        total = sum(len(g.get("runners", [])) for g in orphans)
        if (
            QMessageBox.question(
                self,
                "Remover runners de consoles fechados",
                f"Remover {total} runner(s) de {len(orphans)} console(s) "
                "fechado(s)?\n\n"
                + "\n".join(f"  • {g.get('label') or g.get('sid')}" for g in orphans),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        for g in orphans:
            self._on_remove(g["sid"])
        self._render()
