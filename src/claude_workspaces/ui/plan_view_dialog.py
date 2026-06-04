"""Visualização do plano (plan mode) de uma sessão Claude: markdown
renderizado, com atalho pra abrir o .md como aba central do editor.

Não-modal — o usuário pode deixar aberto enquanto acompanha a execução
do plano no console.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..plan_files import PlanInfo

log = logging.getLogger(__name__)


class PlanViewDialog(QDialog):
    def __init__(
        self,
        info: PlanInfo,
        open_in_editor: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._open_in_editor = open_in_editor
        self.setWindowTitle(f"Plano: {info.title}")
        self.setModal(False)
        self.resize(760, 680)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ---------- Header ----------
        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel(f"<h2 style='margin:0;'>📋 {info.title}</h2>")
        title.setWordWrap(True)
        header.addWidget(title, stretch=1)
        if open_in_editor is not None:
            edit_btn = self._mk_action_btn(
                "📂  Abrir no editor", "Abrir o .md como aba central do editor",
            )
            edit_btn.clicked.connect(self._open_editor)
            header.addWidget(edit_btn)
        copy_btn = self._mk_action_btn(
            "📋  Copiar caminho", "Copiar o caminho do arquivo pro clipboard",
        )
        copy_btn.clicked.connect(self._copy_path)
        header.addWidget(copy_btn)
        outer.addLayout(header)

        meta = QLabel(
            f"<span style='color:#888;'>"
            f"<code style='color:#6aa9e0;'>{info.path}</code>"
            f"</span>"
        )
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(meta)

        # ---------- Body (markdown) ----------
        self._body_view = QTextBrowser()
        self._body_view.setOpenExternalLinks(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._body_view.setFont(font)
        outer.addWidget(self._body_view, stretch=1)
        self.reload()

        # ---------- Footer ----------
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def reload(self, info: PlanInfo | None = None) -> None:
        """Re-renderiza o markdown (plano pode ter sido reescrito)."""
        if info is not None:
            self._info = info
            self.setWindowTitle(f"Plano: {info.title}")
        self._body_view.setMarkdown(self._info.read_markdown())

    def _mk_action_btn(self, text: str, tooltip: str) -> QToolButton:
        """Botão de ação uniforme — mesmo padrão do SkillDetailDialog."""
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setAutoRaise(False)
        btn.setMinimumHeight(28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _open_editor(self) -> None:
        if self._open_in_editor is not None:
            self._open_in_editor(str(self._info.path))

    def _copy_path(self) -> None:
        QGuiApplication.clipboard().setText(str(self._info.path))
        self.setWindowTitle("✓ caminho copiado")
