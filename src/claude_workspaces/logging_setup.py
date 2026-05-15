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

    def handler(mode, _context, message: str) -> None:
        qt_logger.log(qt_level.get(mode, logging.INFO), message)

    qInstallMessageHandler(handler)
