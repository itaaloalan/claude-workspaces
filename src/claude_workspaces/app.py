import logging
import os
import sys

# Sob KDE Plasma 6 Wayland, cada subprocesso do QtWebEngineProcess
# registra surface wayland própria com `--application-name=Claude
# Workspaces` e aparece como janela vazia na overview (Meta+W). Forçar
# o Chromium embarcado pra X11/XWayland mantém o app principal no
# Wayland (sem perder DPI/HiDPI) mas evita as surfaces fantasmas dos
# renderers. Precisa ser setado ANTES de qualquer import do QtWebEngine.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ozone-platform=x11")

from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .logging_setup import setup_logging  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402


def _build_dark_palette() -> QPalette:
    """Palette dark consistente — sobrescreve o tema do desktop (KDE)
    que estava deixando QListWidget items quase invisíveis. Define
    Active + Inactive + Disabled pra todos os roles que importam."""
    pal = QPalette()
    base = {
        QPalette.ColorRole.Window: "#1a1a1a",
        QPalette.ColorRole.WindowText: "#e6e6e6",
        QPalette.ColorRole.Base: "#181818",
        QPalette.ColorRole.AlternateBase: "#1f1f1f",
        QPalette.ColorRole.Text: "#e6e6e6",
        QPalette.ColorRole.PlaceholderText: "#888888",
        QPalette.ColorRole.ToolTipBase: "#1f1f1f",
        QPalette.ColorRole.ToolTipText: "#e6e6e6",
        QPalette.ColorRole.Button: "#1f1f1f",
        QPalette.ColorRole.ButtonText: "#e6e6e6",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#6aa9e0",
        QPalette.ColorRole.LinkVisited: "#a48ad6",
        QPalette.ColorRole.Highlight: "#3d6ea8",
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    disabled_overrides = {
        QPalette.ColorRole.WindowText: "#777777",
        QPalette.ColorRole.Text: "#777777",
        QPalette.ColorRole.ButtonText: "#777777",
        QPalette.ColorRole.HighlightedText: "#bbbbbb",
    }
    for role, hexv in base.items():
        c = QColor(hexv)
        pal.setColor(QPalette.ColorGroup.Active, role, c)
        pal.setColor(QPalette.ColorGroup.Inactive, role, c)
        pal.setColor(QPalette.ColorGroup.Disabled, role, c)
    for role, hexv in disabled_overrides.items():
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(hexv))
    return pal


def main() -> int:
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Iniciando Claude Workspaces")

    from .claude_probe import run_probe
    run_probe()

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Workspaces")
    app.setApplicationDisplayName("Claude Workspaces")
    app.setOrganizationName("claude-workspaces")
    app.setDesktopFileName("claude-workspaces")
    # Fusion é o estilo Qt cross-platform que respeita QSS/QPalette de
    # forma consistente. O estilo nativo do KDE (Breeze) estava ignorando
    # nossas customizações de cor em alguns widgets, deixando texto
    # cinza-escuro em fundo cinza-escuro.
    app.setStyle("Fusion")
    app.setPalette(_build_dark_palette())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
