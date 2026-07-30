"""Aba central de diff — estilo Orca: duplo-clique num arquivo
modificado do painel Git abre o diff como aba no painel central
(ao lado do Console IA), com refresh e toggle inline/lado-a-lado.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme
from ..git_status import get_diff
from .diff_web_view import DiffWebView
from .icons import ic

_HDR_BTN_QSS = (
    "QPushButton { background: transparent; border: 0; border-radius: 4px; "
    f"color: {theme.TEXT_FAINT}; padding: 2px 8px; font-size: 11px; }}"
    f"QPushButton:hover {{ background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY}; }}"
    f"QPushButton:checked {{ background: {theme.PRIMARY_SELECTION_BG}; "
    f"color: {theme.TEXT_PRIMARY}; }}"
).replace("}}", "}")


class DiffTab(QWidget):
    """Diff de UM arquivo (working tree vs HEAD/index) numa aba central."""

    def __init__(
        self,
        folder: str,
        rel_path: str,
        staged: bool = False,
        parent: QWidget | None = None,
        provider=None,
        header_suffix: str = "(diff)",
    ) -> None:
        """`provider` opcional: callable() -> str com o texto do diff —
        usado pela seção COMMITTED ON BRANCH (diff base..HEAD) no lugar
        do diff do working tree."""
        super().__init__(parent)
        self.folder = folder
        self.rel_path = rel_path
        self.staged = staged
        self._provider = provider
        self._header_suffix = header_suffix

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(
            f"background: {theme.BG_DARKER}; "
            f"border-bottom: 1px solid {theme.BORDER_SOFT};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(6)

        path_lbl = QLabel(f"{Path(folder).name} · {rel_path} {self._header_suffix}")
        path_lbl.setStyleSheet(
            f"color: {theme.TEXT_FADED}; font-size: {theme.FONT_SM}px; border: 0;"
        )
        path_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        hl.addWidget(path_lbl, 1)

        self._inline_btn = QPushButton("Inline")
        self._inline_btn.setCheckable(True)
        self._inline_btn.setChecked(True)
        self._inline_btn.setStyleSheet(_HDR_BTN_QSS)
        self._inline_btn.clicked.connect(
            lambda: self._set_format("line-by-line")
        )
        hl.addWidget(self._inline_btn)

        self._side_btn = QPushButton("Lado a lado")
        self._side_btn.setCheckable(True)
        self._side_btn.setStyleSheet(_HDR_BTN_QSS)
        self._side_btn.clicked.connect(lambda: self._set_format("side-by-side"))
        hl.addWidget(self._side_btn)

        refresh_btn = QPushButton()
        refresh_btn.setIcon(ic("ph.arrow-clockwise", color=theme.TEXT_FAINT))
        refresh_btn.setIconSize(QSize(12, 12))
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setToolTip("Recarregar o diff")
        refresh_btn.setStyleSheet(_HDR_BTN_QSS)
        refresh_btn.clicked.connect(self.refresh)
        hl.addWidget(refresh_btn)

        outer.addWidget(header)

        self._web = DiffWebView()
        outer.addWidget(self._web, stretch=1)

        self.refresh()

    def _set_format(self, fmt: str) -> None:
        self._inline_btn.setChecked(fmt == "line-by-line")
        self._side_btn.setChecked(fmt == "side-by-side")
        self._web.set_output_format(fmt)

    def refresh(self) -> None:
        name = self.rel_path.rsplit("/", 1)[-1]
        if self._provider is not None:
            text = self._provider()
        else:
            text = get_diff(
                self.folder, self.rel_path, staged=self.staged, context=3
            )
        self._web.show_diff(text or "", name)
