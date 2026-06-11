"""ResourceDialog — gerenciador de RAM/CPU do app e seus processos.

Aberto pelo segmento de recursos da status bar. Lista, ordenado por RAM,
cada runner/console + o navegador embutido + o app, com %CPU e botão de
encerrar nos que dá (runners/consoles). Um botão "Liberar RAM" roda a
faxina não-destrutiva (`ProcessMonitor.free_memory`) e relata quanto saiu.

Tudo é injetado: o diálogo não conhece a MainWindow, só callbacks.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..process_monitor import (
    CAT_APP,
    CAT_CONSOLE,
    CAT_RUNNER,
    CAT_WEBENGINE,
    FreeResult,
    ProcGroup,
    Snapshot,
    human_bytes,
)
from . import theme

_CAT_ICON = {
    CAT_RUNNER: "▶",
    CAT_CONSOLE: "🤖",
    CAT_WEBENGINE: "🌐",
    CAT_APP: "🪟",
}

_STOP_BTN_QSS = (
    "QPushButton { background: transparent; color: #9aa0a6; "
    "border: 1px solid #2c2c2c; border-radius: 4px; padding: 2px 10px; "
    "font-size: 11px; }"
    "QPushButton:hover { color: #e06c75; border-color: #e06c75; }"
)

_FREE_BTN_QSS = (
    "QPushButton { background: #1f1f1f; color: #e6e6e6; "
    "border: 1px solid #2c2c2c; border-radius: 5px; padding: 5px 14px; "
    "font-size: 12px; font-weight: 600; }"
    "QPushButton:hover { border-color: #5ac35a; color: #fff; }"
    "QPushButton:disabled { color: #555; }"
)


def _bar_color(rss: int) -> str:
    # Verde até ~500MB, amber até ~1.2GB, vermelho acima — por grupo.
    if rss < 500 * 1024 * 1024:
        return theme.SUCCESS
    if rss < 1200 * 1024 * 1024:
        return theme.WARNING
    return theme.DANGER


class ResourceDialog(QDialog):
    def __init__(
        self,
        snapshot_provider: Callable[[], Snapshot],
        on_free: Callable[[], FreeResult],
        on_stop: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = snapshot_provider
        self._on_free = on_free
        self._on_stop = on_stop
        self.setWindowTitle("Gerenciador de recursos")
        self.setMinimumSize(620, 460)
        self.setStyleSheet(f"QDialog {{ background: {theme.BG_PANEL}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        self._summary = QLabel("")
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._summary.setStyleSheet("font-size: 13px;")
        outer.addWidget(self._summary)

        hint = QLabel(
            "Consumo do app e de tudo que ele iniciou (runners, consoles e o "
            "navegador embutido). Encerre o que estiver pesado, ou use "
            "<b>Liberar RAM</b> pra recolher processos moribundos e devolver "
            "memória ao sistema."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 4, 0, 4)
        self._rows.setSpacing(6)
        scroll.setWidget(self._rows_host)
        outer.addWidget(scroll, stretch=1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 11px;")
        outer.addWidget(self._status)

        footer = QHBoxLayout()
        self._free_btn = QPushButton("🧹 Liberar RAM")
        self._free_btn.setStyleSheet(_FREE_BTN_QSS)
        self._free_btn.setToolTip(
            "Recolhe processos moribundos (zumbis), roda o coletor de lixo do "
            "Python e devolve memória livre ao sistema. Não para runners."
        )
        self._free_btn.clicked.connect(self._do_free)
        footer.addWidget(self._free_btn)
        footer.addStretch(1)
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        # Auto-refresh enquanto aberto — o %CPU só faz sentido com amostras
        # repetidas (é delta entre ticks).
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._render)
        self._timer.start()
        self._max_rss = 1
        self._render()

    # ---- render ------------------------------------------------------------

    def _render(self) -> None:
        snap = self._provider()
        self._max_rss = max((g.rss for g in snap.groups), default=1) or 1

        zomb = (
            f" · <span style='color:{theme.DANGER}'>{snap.n_zombies} moribundo(s)</span>"
            if snap.n_zombies
            else ""
        )
        self._summary.setText(
            f"<span style='color:{theme.TEXT_PRIMARY};font-weight:700'>"
            f"RAM {human_bytes(snap.total_rss)}</span>"
            f" <span style='color:{theme.TEXT_FAINT}'>·</span> "
            f"<span style='color:{theme.INFO};font-weight:600'>"
            f"CPU {snap.total_cpu:.0f}%</span>"
            f" <span style='color:{theme.TEXT_FAINT}'>·</span> "
            f"<span style='color:{theme.TEXT_FADED}'>{snap.n_procs} processos</span>"
            f"{zomb}"
        )

        while self._rows.count():
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for g in snap.groups:
            self._rows.addWidget(self._make_row(g))
        self._rows.addStretch(1)

    def _make_row(self, g: ProcGroup) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background: #161616; border: 1px solid #242424; "
            "border-radius: 6px; }"
            "QLabel { background: transparent; border: 0; }"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 7, 10, 7)
        h.setSpacing(10)

        icon = QLabel(_CAT_ICON.get(g.category, "•"))
        icon.setStyleSheet("font-size: 14px;")
        h.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        title_txt = g.label
        if g.zombies:
            title_txt += f"  <span style='color:{theme.DANGER}'>⚠ {g.zombies} moribundo(s)</span>"
        title = QLabel(title_txt)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;"
        )
        title.setWordWrap(True)
        col.addWidget(title)

        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setMaximum(self._max_rss)
        bar.setValue(g.rss)
        color = _bar_color(g.rss)
        bar.setStyleSheet(
            "QProgressBar { background: #202020; border: 0; border-radius: 3px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )
        bar_row.addWidget(bar, stretch=1)
        meta = QLabel(
            f"{human_bytes(g.rss)}  ·  CPU {g.cpu:.0f}%  ·  "
            f"{g.count} proc{'s' if g.count != 1 else ''}"
        )
        meta.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        bar_row.addWidget(meta, 0)
        col.addLayout(bar_row)
        h.addLayout(col, stretch=1)

        if g.stoppable:
            stop = QPushButton("⏹ Encerrar")
            stop.setStyleSheet(_STOP_BTN_QSS)
            stop.clicked.connect(lambda _c=False, gr=g: self._confirm_stop(gr))
            h.addWidget(stop, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    # ---- ações -------------------------------------------------------------

    def _confirm_stop(self, g: ProcGroup) -> None:
        if g.pid is None:
            return
        if (
            QMessageBox.question(
                self,
                "Encerrar processo",
                f"Encerrar “{g.label}”?\n\n"
                f"Usa {human_bytes(g.rss)} de RAM. "
                "O runner/console será parado (dá pra subir de novo depois).",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._on_stop(g.pid)
        except Exception:  # noqa: BLE001 — UI não pode quebrar por isso
            pass
        self._status.setStyleSheet(f"color: {theme.TEXT_FADED}; font-size: 11px;")
        self._status.setText(f"Encerrando “{g.label}”…")
        QTimer.singleShot(400, self._render)

    def _do_free(self) -> None:
        self._free_btn.setEnabled(False)
        res = self._on_free()
        parts = []
        if res.freed_rss > 0:
            parts.append(f"{human_bytes(res.freed_rss)} devolvidos ao sistema")
        if res.reaped_zombies:
            parts.append(f"{res.reaped_zombies} processo(s) moribundo(s) recolhido(s)")
        if res.gc_collected:
            parts.append(f"{res.gc_collected} objeto(s) coletado(s)")
        msg = "✓ " + (" · ".join(parts) if parts else "Nada a liberar agora.")
        self._status.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 11px;")
        self._status.setText(msg)
        self._render()
        QTimer.singleShot(600, lambda: self._free_btn.setEnabled(True))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        super().closeEvent(event)
