import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "claude-workspaces"


def log_file() -> Path:
    return state_dir() / "app.log"


def perf_log_file() -> Path:
    """Log de métricas de performance (silo separado do app.log)."""
    return state_dir() / "perf.log"


def setup_logging(level: int = logging.INFO) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)

    sys.excepthook = _excepthook

    _install_qt_handler()

    logging.getLogger(__name__).info("Logging inicializado — arquivo: %s", log_file())


def _excepthook(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("uncaught").error(
        "Exceção não tratada", exc_info=(exc_type, exc_value, exc_traceback)
    )


def _install_qt_handler() -> None:
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    qt_level = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
        QtMsgType.QtSystemMsg: logging.WARNING,
    }
    qt_logger = logging.getLogger("qt")

    # Dedup: warnings do Qt repetem a MESMA mensagem centenas de vezes por
    # sessão (ex.: "Could not parse stylesheet of object QPushButton(0x...)"
    # a cada re-polish do widget). Normalizamos o ponteiro pra agrupar e
    # logamos as N primeiras ocorrências; depois, só um resumo a cada 100.
    _seen: dict[str, int] = {}
    _MAX_REPEATS = 3

    def _norm(message: str) -> str:
        import re
        return re.sub(r"0x[0-9a-fA-F]+", "0x…", message)

    def handler(mode, _context, message: str) -> None:
        level = qt_level.get(mode, logging.INFO)
        if level < logging.WARNING:
            qt_logger.log(level, message)
            return
        key = _norm(message)
        n = _seen[key] = _seen.get(key, 0) + 1
        if n > _MAX_REPEATS:
            if n % 100 == 0:
                qt_logger.log(level, "%s (repetida %dx — suprimida)", key, n)
            return
        # Stylesheet inválida: o Qt só dá o ponteiro do widget, inútil pra
        # achar o culpado. O parse acontece dentro do setStyleSheet/polish,
        # então o stack Python aponta a linha que setou a QSS quebrada.
        if "parse stylesheet" in message.lower():
            import traceback
            stack = "".join(traceback.format_stack(limit=8)[:-1])
            qt_logger.log(level, "%s\nstack (origem provável):\n%s", message, stack)
            return
        qt_logger.log(level, message)

    qInstallMessageHandler(handler)
