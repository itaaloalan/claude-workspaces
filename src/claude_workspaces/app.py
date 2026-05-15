import logging
import sys

from PySide6.QtWidgets import QApplication

from .logging_setup import setup_logging
from .ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Iniciando Claude Workspaces")

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Workspaces")
    app.setApplicationDisplayName("Claude Workspaces")
    app.setOrganizationName("claude-workspaces")
    app.setDesktopFileName("claude-workspaces")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
