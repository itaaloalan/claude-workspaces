"""SidebarFooter — rodapé compacto (28px) com painéis expansíveis.

Substitui os blocos inline de: stats de uso, find-file, MinimizeTray,
botão "+ Novo Workspace" e version label — todos agrupados num rodapé
discreto. Chips no footer abrem painéis acima quando clicados.

API pública compatível com sidebar_builder (reassigned attributes):
  context_status_label       — QLabel com rich text de uso
  context_status_refresh_btn — QPushButton ⟳
  context_status_updated_label — QLabel timestamp
  usage_detail_panel         — proxy: main_window chama setVisible(T/F)
  version_label              — _ClickableLabel
  minimized_tray             — MinimizeTray
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme
from .minimize_tray import MinimizeTray

_RE_COOLDOWN = re.compile(r"cooldown\s+\d+[mh]")
_RE_HOURS_PCT = re.compile(r"\d+h\s+\d+%")
_RE_PCT = re.compile(r"\d+%")


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _UsageLabel(QLabel):
    """QLabel que atualiza o chip de uso no footer ao receber setText."""

    def __init__(self, chip: QPushButton) -> None:
        super().__init__("")
        self._chip = chip

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        plain = re.sub(r"<[^>]+>", "", text)
        m = _RE_COOLDOWN.search(plain)
        if m:
            self._chip.setText(m.group(0))
            return
        m = _RE_HOURS_PCT.search(plain)
        if m:
            self._chip.setText(m.group(0))
            return
        m = _RE_PCT.search(plain)
        if m:
            self._chip.setText(m.group(0))


class _UsageVisibilityProxy(QWidget):
    """Proxy: main_window chama setVisible(True/False) aqui.
    Quando True → mostra chip de uso no footer.
    Quando False → esconde chip e colapsa painel de detalhe."""

    def __init__(self, chip: QPushButton, detail: QWidget) -> None:
        super().__init__()
        self._chip = chip
        self._detail = detail

    def setVisible(self, visible: bool) -> None:  # type: ignore[override]
        # NÃO chama super() — proxy sem parent apareceria como janela flutuante.
        self._chip.setVisible(visible)
        if not visible:
            self._chip.setChecked(False)
            self._detail.setVisible(False)


class _RunnerFooterRow(QWidget):
    def __init__(
        self,
        workspace_id: str,
        runner_id: str,
        name: str,
        state: str,
        status: str,
        url: str,
        cwd: str,
        on_open: Callable[[str, str], None],
        on_toggle: Callable[[str, str], None],
        on_restart: Callable[[str, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace_id = workspace_id
        self._runner_id = runner_id
        self._on_open = on_open
        self._on_toggle = on_toggle
        self._on_restart = on_restart
        tip = "Abrir runner no painel central"
        if cwd:
            tip = f"Diretório: {cwd}\n{tip}"
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tip)
        self.setStyleSheet(
            "QWidget { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,14); "
            "border-radius: 6px; } QWidget QLabel { background: transparent; border: 0; } "
            "QWidget QPushButton { background: transparent; border: 0; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 5, 4)
        layout.setSpacing(6)

        color = theme.SUCCESS if state == "running" else theme.TEXT_FAINT
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 10px;")
        layout.addWidget(dot)

        sub = status or ("rodando" if state == "running" else "parado")
        if cwd:
            from pathlib import Path
            sub = f"{sub} · 📁 {Path(cwd).name}"
        if url:
            sub = f"{sub} · {url}"
        text = QLabel(
            f"<span style='color:{theme.TEXT_PRIMARY}; font-weight:650;'>{name or '(runner)'}</span>"
            f"<br><span style='color:{theme.TEXT_FAINT}; font-size:10px;'>{sub}</span>"
        )
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(text, stretch=1)

        self._restart_btn = self._action_btn("↻", "Reiniciar runner")
        self._restart_btn.clicked.connect(
            lambda _=False: self._on_restart(self._workspace_id, self._runner_id)
        )
        layout.addWidget(self._restart_btn)

        action_text = "■" if state == "running" else "▶"
        action_tip = "Parar runner" if state == "running" else "Iniciar runner"
        self._toggle_btn = self._action_btn(action_text, action_tip)
        self._toggle_btn.clicked.connect(
            lambda _=False: self._on_toggle(self._workspace_id, self._runner_id)
        )
        layout.addWidget(self._toggle_btn)

    def _action_btn(self, text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setToolTip(tooltip)
        btn.setFixedHeight(20)
        btn.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_FAINT}; font-size: 10px; padding: 1px 5px; }}"
            f"QPushButton:hover {{ color: {theme.SUCCESS}; }}"
        )
        return btn

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(self._workspace_id, self._runner_id)
        super().mousePressEvent(event)


_CHIP_QSS = (
    "QPushButton { background: #1b1b1b; "
    f"color: {theme.TEXT_FAINT}; border: 1px solid #2a2a2a; "
    f"border-radius: 5px; font-size: 9px; font-weight: 650; "
    f"padding: 1px 6px; max-height: 18px; }}"
    f"QPushButton:hover {{ border-color: {theme.PRIMARY}; color: {theme.TEXT_LINK}; }}"
    f"QPushButton:checked {{ background: {theme.BG_DARKER}; "
    f"border-color: {theme.TEXT_LINK}; color: {theme.TEXT_LINK}; }}"
)

_PANEL_QSS = (
    f"QWidget#FooterPanel {{ background: {theme.BG_PANEL}; "
    f"border-top: 1px solid {theme.BORDER}; }}"
)


class SidebarFooter(QWidget):
    """Rodapé compacto da sidebar com chips e painéis expansíveis."""

    console_runner_requested = Signal(str, str)  # workspace_id, runner_id
    runner_toggle_requested = Signal(str, str)  # workspace_id, runner_id
    runner_restart_requested = Signal(str, str)  # workspace_id, runner_id
    # 🗑 do header da seção "console": remover todos os runners do console
    # ativo do workspace exibido.
    console_runners_remove_requested = Signal(str)  # workspace_id
    # ⬇ do header da seção "console": subir a stack do workspace no
    # console ativo (copia runners com remap de porta e inicia).
    console_stack_raise_requested = Signal(str)  # workspace_id

    def __init__(
        self,
        on_version_clicked: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_version_clicked = on_version_clicked
        self._runner_workspace_id = ""
        self._runner_collapsed_workspace_id = ""
        # Colapso por seção do painel de runners ("workspace"/"console") —
        # em memória: sobrevive aos refreshes de status, não ao restart.
        self._runner_scope_collapsed: dict[str, bool] = {}
        self._last_runner_rows: list[tuple] = []
        # Há console aberto/focado no workspace exibido (mostra a seção
        # console com o ⬇ mesmo sem cópias).
        self._console_active = False
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Chip criado antes do painel pra _UsageLabel poder receber a referência.
        self._usage_chip = QPushButton("uso")
        self._usage_chip.setCheckable(True)
        self._usage_chip.setVisible(False)
        self._usage_chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._usage_chip.setToolTip("Ver detalhes de uso do backend de IA")
        self._usage_chip.setStyleSheet(_CHIP_QSS)
        self._usage_chip.clicked.connect(self._toggle_usage)

        self._runner_chip = QPushButton("runners")
        self._runner_chip.setCheckable(True)
        self._runner_chip.setVisible(False)
        self._runner_chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._runner_chip.setToolTip("Runners do workspace selecionado")
        self._runner_chip.setStyleSheet(_CHIP_QSS)
        self._runner_chip.clicked.connect(self._toggle_runners)

        # ── Painel: detalhe de uso ──────────────────────────────────────
        self._usage_panel = QWidget()
        self._usage_panel.setObjectName("FooterPanel")
        self._usage_panel.setStyleSheet(_PANEL_QSS)
        self._usage_panel.setVisible(False)
        up_layout = QVBoxLayout(self._usage_panel)
        up_layout.setContentsMargins(8, 6, 8, 4)
        up_layout.setSpacing(2)

        up_row = QHBoxLayout()
        up_row.setContentsMargins(0, 0, 0, 0)
        up_row.setSpacing(6)

        self.context_status_label = _UsageLabel(self._usage_chip)
        self.context_status_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FADED}; font-size: 11px; }}"
        )
        self.context_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.context_status_label.setWordWrap(True)
        up_row.addWidget(self.context_status_label, stretch=1)

        self.context_status_refresh_btn = QPushButton("⟳")
        self.context_status_refresh_btn.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        self.context_status_refresh_btn.setToolTip(
            "Forçar sincronização do uso do plano com /api/oauth/usage"
        )
        self.context_status_refresh_btn.setFlat(True)
        self.context_status_refresh_btn.setFixedSize(20, 20)
        self.context_status_refresh_btn.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_FAINT}; background: transparent; "
            "border: none; font-size: 13px; padding: 0px; }"
            f"QPushButton:hover {{ color: {theme.TEXT_PRIMARY}; }}"
            "QPushButton:disabled { color: #555; }"
        )
        up_row.addWidget(
            self.context_status_refresh_btn,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        up_layout.addLayout(up_row)

        self.context_status_updated_label = QLabel("")
        self.context_status_updated_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_DISABLED}; font-size: 9px; }}"
        )
        self.context_status_updated_label.setVisible(False)
        up_layout.addWidget(self.context_status_updated_label)

        outer.addWidget(self._usage_panel)

        self._runner_panel = QWidget()
        self._runner_panel.setObjectName("FooterPanel")
        self._runner_panel.setStyleSheet(_PANEL_QSS)
        self._runner_panel.setVisible(False)
        rp_layout = QVBoxLayout(self._runner_panel)
        rp_layout.setContentsMargins(8, 6, 8, 6)
        rp_layout.setSpacing(5)

        runner_head = QLabel("Runners")
        runner_head.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 700; "
            "letter-spacing: 0.5px;"
        )
        rp_layout.addWidget(runner_head)

        self._runner_rows_widget = QWidget()
        self._runner_rows = QVBoxLayout(self._runner_rows_widget)
        self._runner_rows.setContentsMargins(0, 0, 0, 0)
        self._runner_rows.setSpacing(4)
        rp_layout.addWidget(self._runner_rows_widget)
        outer.addWidget(self._runner_panel)

        # ── Painel: minimizados ─────────────────────────────────────────
        self._min_panel = QWidget()
        self._min_panel.setObjectName("FooterPanel")
        self._min_panel.setStyleSheet(_PANEL_QSS)
        self._min_panel.setVisible(False)
        mp_layout = QVBoxLayout(self._min_panel)
        mp_layout.setContentsMargins(0, 0, 0, 0)
        mp_layout.setSpacing(0)

        self.minimized_tray = _TrackedMinimizeTray(self._on_min_count_changed)
        mp_layout.addWidget(self.minimized_tray)
        # show() só após addWidget — garante que o widget já tem parent
        # (sem parent, show() abriria como janela top-level)
        self.minimized_tray.show()
        outer.addWidget(self._min_panel)

        # ── Separador ───────────────────────────────────────────────────
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        outer.addWidget(sep)

        # ── Footer bar (sempre visível, 28px) ───────────────────────────
        footer_bar = QWidget()
        footer_bar.setFixedHeight(28)
        footer_bar.setStyleSheet("QWidget { background: #171717; }")
        fb = QHBoxLayout(footer_bar)
        fb.setContentsMargins(8, 0, 6, 0)
        fb.setSpacing(4)

        self.version_label = _ClickableLabel(f"v{__version__}  ·  notas")
        self.version_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_FAINT}; font-size: 10px; }}"
            f"QLabel:hover {{ color: {theme.TEXT_LINK}; }}"
        )
        self.version_label.setToolTip(
            "Ver o que mudou nesta versão e o histórico completo"
        )
        self.version_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if self._on_version_clicked:
            self.version_label.clicked.connect(self._on_version_clicked)
        fb.addWidget(self.version_label, stretch=1)

        fb.addWidget(self._usage_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        fb.addWidget(self._runner_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self._min_chip = QPushButton("0 min")
        self._min_chip.setCheckable(True)
        self._min_chip.setVisible(False)
        self._min_chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._min_chip.setToolTip("Workspaces minimizados")
        self._min_chip.setStyleSheet(_CHIP_QSS)
        self._min_chip.clicked.connect(self._toggle_min)
        fb.addWidget(self._min_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(footer_bar)

        # Proxy que main_window usa para setVisible no "context container"
        self.usage_detail_panel = _UsageVisibilityProxy(
            self._usage_chip, self._usage_panel
        )

    # ── Slots internos ──────────────────────────────────────────────────

    def _toggle_usage(self, checked: bool) -> None:
        if checked and self._min_panel.isVisible():
            self._min_panel.setVisible(False)
            self._min_chip.setChecked(False)
        self._usage_panel.setVisible(checked)

    def _toggle_runners(self, checked: bool) -> None:
        if checked and self._min_panel.isVisible():
            self._min_panel.setVisible(False)
            self._min_chip.setChecked(False)
        if checked:
            self._runner_collapsed_workspace_id = ""
        elif self._runner_workspace_id:
            self._runner_collapsed_workspace_id = self._runner_workspace_id
        self._runner_panel.setVisible(checked)

    def _toggle_min(self, checked: bool) -> None:
        if checked and self._usage_panel.isVisible():
            self._usage_panel.setVisible(False)
            self._usage_chip.setChecked(False)
        if checked and self._runner_panel.isVisible():
            self._runner_panel.setVisible(False)
            self._runner_chip.setChecked(False)
        self._min_panel.setVisible(checked)
        if checked:
            # FlowLayout usa isVisible() que inclui a cadeia de parents.
            # Chips adicionados com painel oculto ficam com height=0 em cache.
            # invalidate()+activate() força recálculo depois que o painel aparece.
            lay = self._min_panel.layout()
            if lay:
                lay.invalidate()
                lay.activate()

    def _on_min_count_changed(self, count: int) -> None:
        if count:
            self._min_chip.setText(f"{count} min")
            self._min_chip.setVisible(True)
        else:
            self._min_chip.setChecked(False)
            self._min_panel.setVisible(False)
            self._min_chip.setVisible(False)

    def set_console_runners(
        self,
        runners: list[tuple[str, str, str, str, str, str, str, str]],
        console_active: bool = False,
    ) -> None:
        """Atualiza a lista contextual de runners do workspace selecionado.

        Tupla: (workspace_id, runner_id, name, state, status, url, cwd,
        scope) — scope ∈ {"workspace", "console"}; cada grupo é renderizado
        sob seu próprio sub-header pra cópias de console não se misturarem
        com os runners default do workspace. `console_active` indica que há
        um console aberto/focado — mostra a seção "console" (com o botão ⬇
        de subir a stack) mesmo sem cópias ainda.
        """
        self._last_runner_rows = list(runners)
        self._console_active = bool(console_active)
        if not runners:
            self._clear_runner_rows()
            self._runner_chip.setChecked(False)
            self._runner_panel.setVisible(False)
            self._runner_chip.setVisible(False)
            self._runner_workspace_id = ""
            return
        workspace_id = runners[0][0]
        workspace_changed = workspace_id != self._runner_workspace_id
        self._runner_workspace_id = workspace_id
        self._runner_chip.setText(f"{len(runners)} runner" + ("s" if len(runners) != 1 else ""))
        self._runner_chip.setVisible(True)
        self._render_runner_rows()
        if workspace_changed or self._runner_collapsed_workspace_id != self._runner_workspace_id:
            self._runner_chip.setChecked(True)
            self._runner_panel.setVisible(True)

    def _clear_runner_rows(self) -> None:
        while self._runner_rows.count():
            item = self._runner_rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render_runner_rows(self) -> None:
        """(Re)renderiza as rows de `_last_runner_rows` agrupadas por scope,
        com sub-headers clicáveis que colapsam/expandem cada seção."""
        self._clear_runner_rows()
        rows = self._last_runner_rows

        def _add_section(scope: str, count: int) -> None:
            collapsed = bool(self._runner_scope_collapsed.get(scope, False))
            arrow = "▸" if collapsed else "▾"
            text = f"{arrow} {scope}" + (f" ({count})" if collapsed else "")
            lbl = _ClickableLabel(text)
            lbl.setStyleSheet(
                f"color: {theme.TEXT_DISABLED}; font-size: 9px; "
                "font-weight: 700; letter-spacing: 0.5px; padding-top: 2px;"
            )
            lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            lbl.setToolTip("Colapsar/expandir esta seção")
            lbl.clicked.connect(
                lambda s=scope: self._toggle_runner_scope(s)
            )
            if scope != "console":
                self._runner_rows.addWidget(lbl)
                return
            # Seção console: label + ⬇ (subir a stack do workspace no
            # console ativo) + 🗑 (remover todos — só quando há cópias).
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)
            rl.addWidget(lbl, stretch=1)

            def _mini_btn(text: str, tooltip: str, hover: str) -> QPushButton:
                b = QPushButton(text)
                b.setFixedSize(18, 16)
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.setToolTip(tooltip)
                b.setStyleSheet(
                    "QPushButton { background: transparent; border: 0; "
                    f"color: {theme.TEXT_DISABLED}; font-size: 10px; }}"
                    f"QPushButton:hover {{ color: {hover}; }}"
                )
                return b

            raise_btn = _mini_btn(
                "⬇",
                "Subir a stack do workspace neste console (copia os "
                "runners com a próxima porta livre e inicia todos)",
                "#5ac38a",
            )
            raise_btn.clicked.connect(
                lambda _c=False: self.console_stack_raise_requested.emit(
                    self._runner_workspace_id
                )
            )
            rl.addWidget(raise_btn)
            if count > 0:
                trash = _mini_btn(
                    "🗑", "Remover todos os runners deste console", "#e06c75"
                )
                trash.clicked.connect(
                    lambda _c=False: self.console_runners_remove_requested.emit(
                        self._runner_workspace_id
                    )
                )
                rl.addWidget(trash)
            self._runner_rows.addWidget(row)

        last_scope = ""
        for workspace_id, runner_id, name, state, status, url, cwd, scope in rows:
            if scope != last_scope:
                count = sum(1 for r in rows if r[7] == scope)
                _add_section(scope, count)
                last_scope = scope
            if self._runner_scope_collapsed.get(scope, False):
                continue
            self._runner_rows.addWidget(
                self._make_runner_row(
                    workspace_id, runner_id, name, state, status, url, cwd
                )
            )
        # Console aberto mas ainda sem cópias → header da seção mesmo
        # assim, pra dar acesso ao ⬇ (subir a stack) direto da sidebar.
        if self._console_active and not any(r[7] == "console" for r in rows):
            _add_section("console", 0)
        self._runner_rows.addStretch(1)

    def _toggle_runner_scope(self, scope: str) -> None:
        self._runner_scope_collapsed[scope] = not self._runner_scope_collapsed.get(
            scope, False
        )
        self._render_runner_rows()

    def _make_runner_row(
        self,
        workspace_id: str,
        runner_id: str,
        name: str,
        state: str,
        status: str,
        url: str,
        cwd: str,
    ) -> QWidget:
        return _RunnerFooterRow(
            workspace_id,
            runner_id,
            name,
            state,
            status,
            url,
            cwd,
            lambda wid, rid: self.console_runner_requested.emit(wid, rid),
            lambda wid, rid: self.runner_toggle_requested.emit(wid, rid),
            lambda wid, rid: self.runner_restart_requested.emit(wid, rid),
        )


class _TrackedMinimizeTray(MinimizeTray):
    """MinimizeTray que notifica quando a contagem de chips muda."""

    def __init__(
        self,
        on_count_changed: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_count_changed = on_count_changed

    def _refresh_visibility(self) -> None:
        # Não propaga hide/show — o painel pai controla isso.
        self._on_count_changed(len(self._chips))
