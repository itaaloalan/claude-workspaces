import logging
import os
import subprocess
import sys

# Sob KDE Plasma 6 Wayland, cada subprocesso do QtWebEngineProcess
# registra surface wayland própria com `--application-name=Claude
# Workspaces` e aparece como janela vazia na overview (Meta+W). Forçar
# o Chromium embarcado pra X11/XWayland mantém o app principal no
# Wayland (sem perder DPI/HiDPI) mas evita as surfaces fantasmas dos
# renderers. Precisa ser setado ANTES de qualquer import do QtWebEngine.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ozone-platform-hint=x11")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from .logging_setup import setup_logging  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402


_GLOBAL_DARK_QSS = """
QMenu {
    background: #1f1f1f;
    color: #e6e6e6;
    border: 1px solid #2c2c2c;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 22px 6px 18px;
    background: transparent;
}
QMenu::item:selected {
    background: #3d6ea8;
    color: #fff;
}
QMenu::item:disabled {
    color: #777;
}
QMenu::separator {
    height: 1px;
    background: #2c2c2c;
    margin: 4px 8px;
}
QToolTip {
    background: #1f1f1f;
    color: #e6e6e6;
    border: 1px solid #2c2c2c;
    padding: 4px 6px;
}
QMessageBox, QInputDialog, QFileDialog {
    background: #181818;
    color: #e6e6e6;
}
QMessageBox QLabel, QInputDialog QLabel {
    color: #e6e6e6;
    background: transparent;
}
/* Scrollbar global — espelha o visual minimalista do viewport do
 * console (terminal.html): 8px, sem track, thumb sutil, hover amarelo.
 * Pega QListWidget/QTreeWidget/QScrollArea/QPlainTextEdit/QTextBrowser
 * etc. de uma vez. */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
    border: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0;
    border: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: rgba(229, 181, 59, 140);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    background: transparent;
    border: 0;
    height: 0;
    width: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {
    background: transparent;
    border: 0;
    width: 0;
    height: 0;
}
QScrollBar::corner {
    background: transparent;
}
"""


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


def _log_ghost_window_diagnostics(log: logging.Logger) -> None:
    """Dump pra investigar 'janelas fantasmas' (retângulos vazios na
    overview do Plasma Wayland). Loga: env vars relevantes, todos
    QWidget top-level com tipo/título/visibilidade/parent, processos
    QtWebEngineProcess do nosso PID, e o que o KWin enxerga como
    janelas nossas via krunner WindowsRunner. Roda em 3 momentos:
    logo após `window.show()`, +500ms, +2000ms — pra capturar
    surfaces criadas lazy pelos renderers do Chromium."""
    pid = os.getpid()
    try:
        log.warning(
            "[GHOST-DIAG] env: XDG_SESSION_TYPE=%s WAYLAND_DISPLAY=%s "
            "DISPLAY=%s QT_QPA_PLATFORM=%s QTWEBENGINE_CHROMIUM_FLAGS=%s "
            "QTWEBENGINE_DISABLE_SANDBOX=%s",
            os.environ.get("XDG_SESSION_TYPE"),
            os.environ.get("WAYLAND_DISPLAY"),
            os.environ.get("DISPLAY"),
            os.environ.get("QT_QPA_PLATFORM"),
            os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"),
            os.environ.get("QTWEBENGINE_DISABLE_SANDBOX"),
        )

        app = QApplication.instance()
        if app is not None:
            for i, w in enumerate(app.topLevelWidgets()):
                cls = type(w).__name__
                title = w.windowTitle() or "(sem título)"
                geom = w.geometry()
                flags = int(w.windowFlags())
                log.warning(
                    "[GHOST-DIAG] toplevel[%d] %s title=%r visible=%s "
                    "geom=%dx%d@%d,%d flags=0x%x parent=%s",
                    i, cls, title, w.isVisible(),
                    geom.width(), geom.height(), geom.x(), geom.y(),
                    flags, type(w.parent()).__name__ if w.parent() else None,
                )

        try:
            ps = subprocess.run(
                ["ps", "--ppid", str(pid), "-o", "pid,cmd"],
                capture_output=True, text=True, timeout=2,
            )
            for line in ps.stdout.strip().splitlines():
                if "QtWebEngine" in line or "webengine" in line.lower():
                    log.warning("[GHOST-DIAG] webengine subproc: %s", line.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass

        try:
            r = subprocess.run(
                ["qdbus6", "--literal", "org.kde.KWin", "/WindowsRunner",
                 "org.kde.krunner1.Match", "claude"],
                capture_output=True, text=True, timeout=2,
            )
            count = r.stdout.count("Claude Workspaces") if r.stdout else 0
            log.warning(
                "[GHOST-DIAG] KWin reporta %d janelas com 'Claude' no título",
                count,
            )
        except (subprocess.TimeoutExpired, OSError):
            log.warning("[GHOST-DIAG] qdbus6/KWin indisponível")
    except Exception:
        log.exception("[GHOST-DIAG] falhou")


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
    # QSS global pra widgets que o Fusion + palette não cobrem direito
    # (QMenu vinha branco em algumas distros, QToolTip idem).
    app.setStyleSheet(_GLOBAL_DARK_QSS)

    window = MainWindow()
    window.show()

    # Diagnóstico das janelas fantasmas em 3 fases — alguns surfaces
    # do Chromium só aparecem depois que os renderers iniciam.
    QTimer.singleShot(0, lambda: _log_ghost_window_diagnostics(log))
    QTimer.singleShot(500, lambda: _log_ghost_window_diagnostics(log))
    QTimer.singleShot(2000, lambda: _log_ghost_window_diagnostics(log))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
