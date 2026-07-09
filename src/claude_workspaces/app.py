import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Sob KDE Plasma 6 Wayland, cada subprocesso do QtWebEngineProcess
# registra surface wayland própria com `--application-name=Claude
# Workspaces` e aparece como janela vazia na overview (Meta+W). Forçar
# o Chromium embarcado pra X11/XWayland mantém o app principal no
# Wayland (sem perder DPI/HiDPI) mas evita as surfaces fantasmas dos
# renderers. Precisa ser setado ANTES de qualquer import do QtWebEngine.
# --process-per-site: todos os consoles e runners carregam o MESMO
# terminal.html (mesma origem file://), então o Chromium agrupa todas as
# QWebEngineView num único processo renderer em vez de 1 por view. Sem
# isso, cada console/runner aberto sobe um processo Chromium próprio
# (~50-440MB cada) e eles nunca morrem — terminate()/closeEvent() só
# encerram o PTY, não destroem a view. Colapsa dezenas de renderers em ~1.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--ozone-platform-hint=x11 --process-per-site",
)

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleFactory,
)

from .logging_setup import setup_logging  # noqa: E402
from .ui import theme  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402

_GLOBAL_DARK_QSS = f"""
QMenu {{
    background: {theme.BG_SURFACE};
    color: {theme.TEXT_PRIMARY};
    border: 1px solid {theme.BORDER_INPUT};
    padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 22px 6px 18px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {theme.PRIMARY};
    color: {theme.TEXT_ON_ACCENT};
}}
QMenu::item:disabled {{
    color: #8b8880;
}}
QMenu::separator {{
    height: 1px;
    background: {theme.BORDER_INPUT};
    margin: 4px 8px;
}}
QToolTip {{
    background: {theme.BG_SURFACE};
    color: {theme.TEXT_PRIMARY};
    border: 1px solid {theme.BORDER_INPUT};
    padding: 4px 6px;
}}
QMessageBox, QInputDialog, QFileDialog {{
    background: {theme.BG_DARK};
    color: {theme.TEXT_PRIMARY};
}}
QMessageBox QLabel, QInputDialog QLabel {{
    color: {theme.TEXT_PRIMARY};
    background: transparent;
}}
/* Scrollbar global — espelha o visual minimalista do viewport do
 * console (terminal.html): 8px, sem track, thumb sutil, hover âmbar.
 * Pega QListWidget/QTreeWidget/QScrollArea/QPlainTextEdit/QTextBrowser
 * etc. de uma vez. */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: rgba(212, 160, 74, 150);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    background: transparent;
    border: 0;
    height: 0;
    width: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {{
    background: transparent;
    border: 0;
    width: 0;
    height: 0;
}}
QScrollBar::corner {{
    background: transparent;
}}
"""


def _tint_white(icon: QIcon, size: int = 16) -> QIcon:
    """Recolore um ícone monocromático pra branco (preservando o alfa).
    Mesmo truque do launch_claude_dialog, agora global via QProxyStyle."""
    pm = icon.pixmap(size, size)
    if pm.isNull():
        return icon
    tinted = QPixmap(pm.size())
    tinted.fill(Qt.GlobalColor.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), QColor("white"))
    p.end()
    return QIcon(tinted)


# Pixmaps de BOTÃO de diálogo (não os ícones de severidade do QMessageBox).
# getattr protege nomes que não existem em todas as versões do Qt.
_DIALOG_BUTTON_PIXMAPS = frozenset(
    sp
    for sp in (
        getattr(QStyle.StandardPixmap, name, None)
        for name in (
            "SP_DialogOkButton", "SP_DialogCancelButton", "SP_DialogCloseButton",
            "SP_DialogSaveButton", "SP_DialogOpenButton", "SP_DialogApplyButton",
            "SP_DialogResetButton", "SP_DialogDiscardButton", "SP_DialogYesButton",
            "SP_DialogNoButton", "SP_DialogHelpButton", "SP_DialogRetryButton",
            "SP_DialogIgnoreButton", "SP_RestoreDefaultsButton",
            "SP_DialogYesToAllButton", "SP_DialogNoToAllButton",
            "SP_DialogSaveAllButton", "SP_DialogAbortButton",
        )
    )
    if sp is not None
)


class _WhiteDialogIconStyle(QProxyStyle):
    """Tinge de branco os ícones dos BOTÕES de diálogo (OK/Cancelar/Sim/Não/
    Close/Save...). Com Fusion + palette dark o Qt os renderizava pretos —
    invisíveis no tema escuro. Só os pixmaps de botão são tingidos; os ícones
    COLORIDOS de severidade do QMessageBox (info/warning/erro) passam intactos.
    """

    def standardIcon(self, standardIcon, option=None, widget=None):  # noqa: N802
        base = super().standardIcon(standardIcon, option, widget)
        if standardIcon in _DIALOG_BUTTON_PIXMAPS:
            return _tint_white(base)
        return base


def _build_dark_palette() -> QPalette:
    """Palette dark consistente — sobrescreve o tema do desktop (KDE)
    que estava deixando QListWidget items quase invisíveis. Define
    Active + Inactive + Disabled pra todos os roles que importam."""
    pal = QPalette()
    base = {
        QPalette.ColorRole.Window: theme.BG_PANEL,
        QPalette.ColorRole.WindowText: theme.TEXT_PRIMARY,
        QPalette.ColorRole.Base: theme.BG_DARK,
        QPalette.ColorRole.AlternateBase: theme.BG_SURFACE,
        QPalette.ColorRole.Text: theme.TEXT_PRIMARY,
        QPalette.ColorRole.PlaceholderText: theme.TEXT_FAINT,
        QPalette.ColorRole.ToolTipBase: theme.BG_SURFACE,
        QPalette.ColorRole.ToolTipText: theme.TEXT_PRIMARY,
        QPalette.ColorRole.Button: theme.BG_SURFACE,
        QPalette.ColorRole.ButtonText: theme.TEXT_PRIMARY,
        QPalette.ColorRole.BrightText: theme.TEXT_BRIGHT,
        QPalette.ColorRole.Link: theme.TEXT_LINK,
        QPalette.ColorRole.LinkVisited: "#a48ad6",
        QPalette.ColorRole.Highlight: theme.PRIMARY,
        QPalette.ColorRole.HighlightedText: theme.TEXT_ON_ACCENT,
    }
    disabled_overrides = {
        QPalette.ColorRole.WindowText: "#8b8880",
        QPalette.ColorRole.Text: "#8b8880",
        QPalette.ColorRole.ButtonText: "#8b8880",
        QPalette.ColorRole.HighlightedText: "#c9c6c0",
    }
    for role, hexv in base.items():
        c = QColor(hexv)
        pal.setColor(QPalette.ColorGroup.Active, role, c)
        pal.setColor(QPalette.ColorGroup.Inactive, role, c)
        pal.setColor(QPalette.ColorGroup.Disabled, role, c)
    for role, hexv in disabled_overrides.items():
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(hexv))
    return pal


def _load_ui_font() -> QFont:
    """Registra a Inter (vendorada em ui/static/fonts/) e monta a fonte
    padrão da UI. Cai em Noto Sans / Sans Serif se o TTF não carregar —
    o terminal (xterm) e os QPlainTextEdit continuam em JetBrains Mono,
    não afetados por isto."""
    font_path = (
        Path(__file__).resolve().parent
        / "ui" / "static" / "fonts" / "Inter-Variable.ttf"
    )
    families: list[str] = []
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
    font = QFont()
    font.setFamilies([*families, "Inter", "Noto Sans", "Sans Serif"])
    font.setPointSize(10)
    return font


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


# NUNCA sobrescrever QApplication.notify() (nem instalar eventFilter no
# objeto QApplication) em Python neste app. Com um override Python, TODO
# evento Qt precisa converter o `receiver` num wrapper Python antes de chamar
# o método — inclusive QObjects internos criados em C++ que nunca tiveram
# wrapper (QQuickWindow do compositor da QtWebEngine, QWebEngineUrlRequestJob,
# QQuickItems...). Criar esse wrapper (PySide::getWrapperForQObject) seta uma
# dynamic property no QObject, o que dispara SINCRONAMENTE um
# QDynamicPropertyChangeEvent pro mesmo objeto → reentra o notify() → tenta
# criar o wrapper que ainda está no meio da construção → SIGSEGV nativo.
# Foi a causa raiz dos crashes de boot/hover/foco de 2026-07-03 (~10
# coredumps, todos com getWrapperForQObject↔doSetProperty reentrantes
# sanduichados pelos frames do QApplicationWrapper::notify). O gate
# `perf.is_enabled()` dentro do método não protegia nada: o wrapping dos
# argumentos acontece no trampolim gerado, ANTES do corpo Python rodar.
# A métrica ui.input_dispatch que vivia aqui foi removida; o StallWatchdog
# (perf_watchdog) cobre o mesmo diagnóstico com stack Python do stall.


def main() -> int:
    boot_t0 = time.perf_counter()
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("Iniciando Claude Workspaces")

    from .backend_probe import run_probe
    from .settings import Settings
    settings = Settings.load()

    # Instrumentação de performance (agregada → perf.log). No-op se desligada.
    from . import perf
    from .logging_setup import perf_log_file
    perf.init(settings.perf_logging_enabled, perf_log_file())

    run_probe(backend=settings.ai_backend)

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Workspaces")
    app.setApplicationDisplayName("Claude Workspaces")
    app.setOrganizationName("claude-workspaces")
    app.setDesktopFileName("claude-workspaces")
    # Fusion é o estilo Qt cross-platform que respeita QSS/QPalette de
    # forma consistente. O estilo nativo do KDE (Breeze) estava ignorando
    # nossas customizações de cor em alguns widgets, deixando texto
    # cinza-escuro em fundo cinza-escuro.
    app.setStyle(_WhiteDialogIconStyle(QStyleFactory.create("Fusion")))
    app.setPalette(_build_dark_palette())
    app.setFont(_load_ui_font())
    # QSS global pra widgets que o Fusion + palette não cobrem direito
    # (QMenu vinha branco em algumas distros, QToolTip idem).
    app.setStyleSheet(_GLOBAL_DARK_QSS)
    # Ícone padrão de TODAS as janelas/diálogos (QDialog, QInputDialog,
    # QMessageBox). Sem isto o Qt renderiza um ícone preto na barra de
    # título — invisível no tema escuro. O SVG é o mesmo do taskbar/menu.
    icon_path = Path(__file__).resolve().parent / "ui" / "static" / "app-icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    log.info(
        "[BOOT-PERF] janela visível em %.0fms",
        (time.perf_counter() - boot_t0) * 1000,
    )

    # Watchdog de stalls do main thread — só com perf ligado, e armado
    # DEPOIS do show() pra não reportar o boot inteiro como stall.
    if settings.perf_logging_enabled:
        from . import perf_watchdog
        QTimer.singleShot(0, perf_watchdog.install)

    # Diagnóstico das janelas fantasmas em 3 fases — alguns surfaces
    # do Chromium só aparecem depois que os renderers iniciam. Opt-in via
    # env: era ~40% das linhas do app.log em TODO boot, enterrando o que
    # importa; liga com CW_GHOST_DIAG=1 quando o sintoma reaparecer.
    if os.environ.get("CW_GHOST_DIAG"):
        QTimer.singleShot(0, lambda: _log_ghost_window_diagnostics(log))
        QTimer.singleShot(500, lambda: _log_ghost_window_diagnostics(log))
        QTimer.singleShot(2000, lambda: _log_ghost_window_diagnostics(log))

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
