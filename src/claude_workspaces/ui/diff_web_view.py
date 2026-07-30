"""Widget de diff rico baseado em webview (diff2html + highlight.js).

Mesmo padrão do TerminalWidget: QWebEngineView + QWebChannel com lazy-load —
o processo Chromium só sobe quando o diff é exibido pela primeira vez, mantendo
o overhead zero enquanto o painel fica oculto.

A classe `DiffBridge` (QObject) é registrada no canal como "bridge" e expõe:
  - Sinal `render_diff(str, str, str)` → JS renderiza o diff.
  - Slot  `frontend_ready()`           ← JS chama quando a página carregou.

`DiffWebView` é o widget de alto nível usado pelo `GitPanel`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

STATIC_DIR = Path(__file__).parent / "static"


class DiffBridge(QObject):
    """Ponte Qt ↔ JS para o visualizador de diff.

    O sinal `render_diff` é emitido do Python para o JS quando há um diff a
    renderizar.  O slot `frontend_ready` é chamado pelo JS quando a página
    terminou de carregar e o canal está conectado.
    """

    # Qt → JS: pede ao JS que renderize o diff
    # (unified_text, output_format, filename)
    render_diff = Signal(str, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ready = False
        self._pending: tuple[str, str, str] | None = None

    @Slot()
    def frontend_ready(self) -> None:
        """Chamado pelo JS quando o canal está conectado e a página pronta."""
        self._ready = True
        if self._pending is not None:
            pending = self._pending
            self._pending = None
            self.render_diff.emit(*pending)

    def request_render(self, unified: str, fmt: str, filename: str) -> None:
        """Envia o diff pro JS; enfileira se o frontend ainda não carregou."""
        if self._ready:
            self.render_diff.emit(unified, fmt, filename)
        else:
            # Guarda como pendente — será despachado em frontend_ready()
            self._pending = (unified, fmt, filename)

    def reset(self) -> None:
        """Reinicia o estado de prontidão (chamado ao recarregar a página)."""
        self._ready = False
        self._pending = None


class DiffWebView(QWidget):
    """Visualizador de diff rico com lazy-load do webview.

    O `QWebEngineView` (processo Chromium) só é criado na primeira vez que
    `show_diff()` é chamado.  Até lá um placeholder escuro ocupa o espaço —
    sem custo de GPU nem processo extra.

    Interface pública:
      show_diff(unified, filename)  — exibe o diff (cria webview se necessário)
      clear_diff()                  — limpa / volta ao placeholder
      set_output_format(fmt)        — 'line-by-line' | 'side-by-side'
      has_diff()                    — True se há diff exibido
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_built = False
        self._output_format = "line-by-line"
        self._current_unified: str = ""
        self._current_filename: str = ""

        self.bridge = DiffBridge(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Placeholder escuro exibido antes do lazy-load
        self._placeholder = QWidget()
        self._placeholder.setStyleSheet("background: #0e0e0e;")
        layout.addWidget(self._placeholder)

        self.view: QWebEngineView | None = None
        self.channel: QWebChannel | None = None

    # ── API pública ─────────────────────────────────────────────────────────

    def show_diff(self, unified: str, filename: str) -> None:
        """Exibe `unified` (git diff unificado) no widget.

        Cria o QWebEngineView na primeira chamada (lazy-load).  Chamadas
        subsequentes apenas re-renderizam sem recriar o webview.
        """
        self._current_unified = unified
        self._current_filename = filename
        self._ensure_view_loaded()
        self.bridge.request_render(unified, self._output_format, filename)

    def clear_diff(self) -> None:
        """Limpa o diff exibido e volta ao placeholder."""
        self._current_unified = ""
        self._current_filename = ""
        if self._view_built and self.bridge._ready:
            self.bridge.render_diff.emit("", self._output_format, "")

    def set_output_format(self, fmt: str) -> None:
        """Alterna entre 'line-by-line' (inline) e 'side-by-side'.

        Re-renderiza o diff atual com o novo formato se houver diff exibido.
        """
        if fmt == self._output_format:
            return
        self._output_format = fmt
        if self._current_unified:
            self.bridge.request_render(
                self._current_unified, fmt, self._current_filename
            )

    def has_diff(self) -> bool:
        """Verdadeiro se há um diff atualmente exibido."""
        return bool(self._current_unified)

    # ── Lazy-load ────────────────────────────────────────────────────────────

    def _ensure_view_loaded(self) -> None:
        """Cria o QWebEngineView + QWebChannel na primeira chamada. Idempotente."""
        if self._view_built:
            return
        self._view_built = True

        self.view = QWebEngineView(self)
        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        # Troca o placeholder pelo webview real
        layout = self.layout()
        layout.removeWidget(self._placeholder)
        self._placeholder.setParent(None)
        self._placeholder.deleteLater()
        self._placeholder = None  # type: ignore[assignment]
        layout.addWidget(self.view)

        html_path = STATIC_DIR / "diff.html"
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))
