"""Helpers centrais de animação da UI.

Regra nº 1: NUNCA aplicar efeito de opacidade/QGraphicsEffect em
container que tenha QWebEngineView (TerminalArea, RunnerArea,
DiffWebView) — quebra a composição do Chromium e trava a UI. Os helpers
aqui são pra widgets opacos comuns (overlays, chips, trays).

`settings.reduce_motion` desliga tudo: os helpers viram no-ops e o
estado final é aplicado na hora.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

_reduce_motion = False

DEFAULT_MS = 120


def set_reduce_motion(value: bool) -> None:
    """Chamado no boot com settings.reduce_motion."""
    global _reduce_motion
    _reduce_motion = bool(value)


def reduce_motion() -> bool:
    return _reduce_motion


def fade_in(widget: QWidget, ms: int = DEFAULT_MS) -> None:
    """Mostra `widget` com fade. Com reduce_motion, mostra direto.
    NÃO usar em containers com QWebEngineView."""
    if _reduce_motion:
        widget.show()
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    widget.show()
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Remove o effect no fim — QGraphicsEffect residual custa composição.
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def fade_out(widget: QWidget, ms: int = DEFAULT_MS) -> None:
    """Esconde `widget` com fade. Com reduce_motion, esconde direto.
    NÃO usar em containers com QWebEngineView."""
    if _reduce_motion:
        widget.hide()
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done() -> None:
        widget.hide()
        widget.setGraphicsEffect(None)

    anim.finished.connect(_done)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
