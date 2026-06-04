"""Painel do right-dock com o plano (plan mode) da sessão ativa.

A MainWindow é quem descobre o plano (scan do transcript fora da UI
thread em `_refresh_active_plan`) e empurra via `set_plan()` — o painel
só renderiza. `set_workspace` faz parte do contrato DockPanel mas aqui
é quase no-op: o plano segue o CONSOLE ativo, não o workspace.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace
from ..plan_files import PlanInfo, find_session_plan

log = logging.getLogger(__name__)


class PlanScanSignals(QObject):
    done = Signal(int, object)  # epoch, PlanInfo | None


class PlanScanTask(QRunnable):
    """Roda `find_session_plan` FORA da UI thread — transcripts podem
    ter centenas de MB (mesmo padrão da SkillsPanel). `epoch` descarta
    resultados obsoletos quando o console ativo troca antes do scan
    anterior terminar."""

    def __init__(self, epoch: int, transcript: Path | None) -> None:
        super().__init__()
        self.epoch = epoch
        self.transcript = transcript
        self.signals = PlanScanSignals()

    def run(self) -> None:
        info: PlanInfo | None = None
        try:
            info = find_session_plan(self.transcript)
        except Exception:
            log.exception("Falha escaneando plano da sessão")
        self.signals.done.emit(self.epoch, info)

_BTN_CSS = (
    "QPushButton {"
    "  background: transparent; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 9px;"
    "  padding: 1px 8px; font-size: 11px;"
    "}"
    "QPushButton:hover { color: #e6e6e6; border-color: #3d6ea8; }"
)


class PlansPanel(QWidget):
    """Mostra o plano da sessão Claude do console ativo, inline."""

    # Pedido pra abrir o plano em janela flutuante (MainWindow conecta).
    open_dialog_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._info: PlanInfo | None = None
        self._on_refresh = on_refresh

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._title_label = QLabel("")
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(
            "color: #c8c8c8; font-size: 12px; font-weight: 600;"
        )
        self._title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        outer.addWidget(self._title_label)

        self._body_view = QTextBrowser()
        self._body_view.setOpenExternalLinks(True)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._body_view.setFont(mono)
        self._body_view.setStyleSheet(
            "QTextBrowser {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6; padding: 6px;"
            "}"
        )
        outer.addWidget(self._body_view, stretch=1)

        footer = QHBoxLayout()
        self._path_label = QLabel("")
        self._path_label.setStyleSheet(
            "color: #777; font-size: 10px; font-family: monospace;"
        )
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        footer.addWidget(self._path_label, stretch=1)
        self._open_btn = QPushButton("Abrir em janela")
        self._open_btn.setStyleSheet(_BTN_CSS)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self.open_dialog_requested.emit)
        footer.addWidget(self._open_btn)
        refresh_btn = QPushButton("↻")
        refresh_btn.setStyleSheet(_BTN_CSS)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setToolTip("Re-escanear o plano da sessão ativa")
        refresh_btn.clicked.connect(self._do_refresh)
        footer.addWidget(refresh_btn)
        outer.addLayout(footer)

        self._rendered_once = False
        self.set_plan(None)

    # ---------- contrato DockPanel ----------

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        if workspace is None:
            self.set_plan(None)

    # ---------- API chamada pela MainWindow ----------

    def set_plan(self, info: PlanInfo | None) -> None:
        """Renderiza o plano (ou placeholder). Curto-circuita se nada
        mudou — chamado a cada refresh de atividade do console."""
        if self._rendered_once:
            if info is None and self._info is None:
                return
            if (
                info is not None
                and self._info is not None
                and info.path == self._info.path
                and info.mtime == self._info.mtime
            ):
                return
        self._rendered_once = True
        self._info = info
        if info is None:
            self._title_label.setText("📋 Plano da sessão")
            self._path_label.setText("")
            self._open_btn.setVisible(False)
            self._body_view.setMarkdown(
                "_Nenhum plano nesta sessão._\n\n"
                "Quando o Claude criar um plano (plan mode), ele aparece "
                "aqui automaticamente."
            )
            return
        self._title_label.setText(f"📋 {info.title}")
        self._path_label.setText(str(info.path))
        self._open_btn.setVisible(True)
        self._body_view.setMarkdown(info.read_markdown())

    def _do_refresh(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()
