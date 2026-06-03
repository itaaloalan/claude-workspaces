"""Spinner reutilizável (frames braille + timer).

Mora num módulo neutro pra que widgets (workspace_details, git_panel) e o
TerminalCoordinator compartilhem os mesmos frames sem importar uns dos outros.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL_MS = 100


class Spinner(QObject):
    """Timer de ~100ms que emite `tick(frame)` enquanto roda.

    `frame()` devolve o caractere atual; `start()`/`stop()` controlam o timer.
    Reusável em labels/placeholders: conecte `tick` pra repintar o texto.
    """

    tick = Signal(str)

    def __init__(
        self, interval_ms: int = SPINNER_INTERVAL_MS, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._advance)

    def frame(self) -> str:
        return SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]

    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._frame = 0

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self.tick.emit(self.frame())
