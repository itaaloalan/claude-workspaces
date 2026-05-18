"""Dialog que mostra release notes da versão atual + histórico completo.

Aberto ao clicar no link de versão na sidebar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..services.changelog import Release, load_releases


class ReleaseNotesDialog(QDialog):
    """Janela com lista de versões à esquerda e notas markdown à direita.

    A versão atual (`__version__`) é selecionada por padrão.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        releases: list[Release] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Histórico de Versões")
        self.resize(820, 560)

        self._releases = releases if releases is not None else load_releases()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QLabel(
            f"<b>Claude Workspaces</b> &nbsp;·&nbsp; versão atual <b>{__version__}</b>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        self._list = QListWidget()
        self._list.setMinimumWidth(160)
        self._list.setMaximumWidth(220)
        self._list.setStyleSheet(
            "QListWidget { background: #1f1f1f; color: #e6e6e6; border: 1px solid #2a2a2a; }"
            "QListWidget::item { padding: 6px 8px; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        splitter.addWidget(self._list)

        self._body = QTextBrowser()
        self._body.setOpenExternalLinks(True)
        self._body.setStyleSheet(
            "QTextBrowser { background: #1a1a1a; color: #e6e6e6;"
            " border: 1px solid #2a2a2a; padding: 8px; }"
        )
        font = QFont()
        font.setPointSize(font.pointSize() + 1)
        self._body.setFont(font)
        splitter.addWidget(self._body)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 620])

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._populate()
        self._list.currentRowChanged.connect(self._on_row_changed)

        self._select_current_version()

    def _populate(self) -> None:
        self._list.clear()
        if not self._releases:
            item = QListWidgetItem("(sem CHANGELOG)")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self._body.setMarkdown(
                "Nenhum `CHANGELOG.md` encontrado. Esperado na raiz do repo."
            )
            return
        for rel in self._releases:
            label = f"{rel.version}"
            if rel.date:
                label += f"   ·   {rel.date}"
            QListWidgetItem(label, self._list)

    def _select_current_version(self) -> None:
        if not self._releases:
            return
        for i, rel in enumerate(self._releases):
            if rel.version == __version__:
                self._list.setCurrentRow(i)
                return
        self._list.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._releases):
            return
        rel = self._releases[row]
        md = self._render_release(rel)
        self._body.setMarkdown(md)

    @staticmethod
    def _render_release(rel: Release) -> str:
        header = f"# Versão {rel.version}"
        if rel.date:
            header += f"\n\n*{rel.date}*"
        body = rel.body_markdown
        if not body:
            body = "_Sem notas registradas para esta versão._"
        return f"{header}\n\n{body}\n"
