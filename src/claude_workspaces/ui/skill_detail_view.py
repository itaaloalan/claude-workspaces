"""Versão widget (não-modal) do detalhe de skill/agente/comando.

Mesma anatomia do SkillDetailDialog, mas pode ser embarcado num split
(catalog view) sem precisar de janela separada.

Quando o item muda, set_item() rebuilda o conteúdo. Sem item, mostra
um placeholder "selecione algo na lista".
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..errors import LaunchError
from ..services.skills_install import available_scopes, install_item
from ..skills_discovery import KIND_LABEL_MAP, ClaudeItem
from ..skills_lint import _parse_frontmatter_raw, lint_item
from ..skills_telemetry import SkillUsage

log = logging.getLogger(__name__)


class SkillDetailView(QWidget):
    def __init__(
        self,
        settings=None,
        workspace_folder: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._workspace_folder = workspace_folder
        self._item: ClaudeItem | None = None
        self._usage: SkillUsage | None = None
        self._catalog_names: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(16, 12, 16, 12)
        self._inner_layout.setSpacing(10)
        self._scroll.setWidget(self._inner)

        self._show_placeholder()

    # ---------- API ----------

    def set_workspace_folder(self, folder: str | None) -> None:
        self._workspace_folder = folder

    def clear(self) -> None:
        self._item = None
        self._show_placeholder()

    def set_item(
        self,
        item: ClaudeItem,
        usage: SkillUsage | None,
        catalog_names: set[str],
        workspace_folder: str | None = None,
    ) -> None:
        self._item = item
        self._usage = usage
        self._catalog_names = catalog_names
        if workspace_folder is not None:
            self._workspace_folder = workspace_folder
        self._render()

    # ---------- Render ----------

    def _clear_layout(self) -> None:
        while self._inner_layout.count():
            child = self._inner_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _show_placeholder(self) -> None:
        self._clear_layout()
        lab = QLabel(
            "Selecione uma skill, agente ou comando na lista à esquerda "
            "pra ver detalhes, lint, telemetria e o conteúdo."
        )
        lab.setStyleSheet("color: #888;")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setWordWrap(True)
        self._inner_layout.addWidget(lab)
        self._inner_layout.addStretch()

    def _render(self) -> None:
        item = self._item
        if not item:
            self._show_placeholder()
            return
        self._clear_layout()

        # Header — título + ações
        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel(f"<h2 style='margin:0;'>{item.invocation}</h2>")
        header.addWidget(title)
        header.addStretch()
        install_btn = self._build_install_button()
        if install_btn:
            header.addWidget(install_btn)
        edit_btn = self._mk_action_btn("✏️  Editar", "Abrir editor visual com validação live")
        edit_btn.clicked.connect(self._open_editor)
        if item.source.startswith("plugin:"):
            edit_btn.setEnabled(False)
            edit_btn.setToolTip("Plugin é read-only — instale localmente pra editar")
        header.addWidget(edit_btn)
        if self._settings is not None:
            play_btn = self._mk_action_btn(
                "▶  Testar…", "Rodar claude --print com este recurso isolado",
            )
            play_btn.clicked.connect(self._open_playground)
            header.addWidget(play_btn)
        copy_btn = self._mk_action_btn(
            f"📋  Copiar {item.invocation}", "Copiar invocação pro clipboard",
        )
        copy_btn.clicked.connect(self._copy_invocation)
        header.addWidget(copy_btn)
        self._inner_layout.addLayout(header)

        meta = QLabel(
            f"<span style='color:#888;'>"
            f"<b>{KIND_LABEL_MAP.get(item.kind, item.kind)}</b> · "
            f"fonte: <code>{item.source_label}</code> · "
            f"<code style='color:#6aa9e0;'>{item.path}</code>"
            f"</span>"
        )
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._inner_layout.addWidget(meta)

        # Lint
        issues = lint_item(item, self._catalog_names)
        if issues:
            box = QGroupBox(f"Lint ({len(issues)} issue(s))")
            box.setStyleSheet("QGroupBox { color: #e6a23c; }")
            box_l = QVBoxLayout(box)
            for i in issues:
                color = (
                    "#e74c3c" if i.severity == "error"
                    else "#e6a23c" if i.severity == "warning"
                    else "#909399"
                )
                lab = QLabel(
                    f"<span style='color:{color};'>{i.badge()} "
                    f"<code>{i.code}</code></span> · {i.message}"
                )
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                box_l.addWidget(lab)
            self._inner_layout.addWidget(box)

        # Telemetria
        usage = self._usage
        if usage and usage.count > 0:
            stats = QLabel(self._usage_summary(usage))
            stats.setStyleSheet("color: #5ac35a;")
            stats.setWordWrap(True)
            self._inner_layout.addWidget(stats)
        elif item.kind in {"skill", "agent"}:
            zumbi = QLabel(
                "<span style='color:#909399;'>👻 zumbi · "
                "nunca foi usada (ou Claude nunca decidiu invocar)</span>"
            )
            self._inner_layout.addWidget(zumbi)

        # Frontmatter
        fm = self._parse_frontmatter()
        if fm:
            fm_box = QGroupBox("Frontmatter")
            fm_l = QFormLayout(fm_box)
            fm_l.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for k, v in fm.items():
                key_lab = QLabel(f"<b>{k}</b>")
                val_lab = QLabel(v)
                val_lab.setWordWrap(True)
                val_lab.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                fm_l.addRow(key_lab, val_lab)
            self._inner_layout.addWidget(fm_box)

        # Body markdown
        body_box = QGroupBox("Conteúdo")
        body_l = QVBoxLayout(body_box)
        body_view = QTextBrowser()
        body_view.setOpenExternalLinks(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        body_view.setFont(font)
        body_view.setMarkdown(self._read_body())
        body_l.addWidget(body_view)
        self._inner_layout.addWidget(body_box, stretch=1)

    # ---------- helpers (mesma lógica do dialog) ----------

    def _mk_action_btn(self, text: str, tooltip: str) -> QToolButton:
        """Botão de ação uniforme — QToolButton text-only, altura fixa."""
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setAutoRaise(False)
        btn.setMinimumHeight(28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build_install_button(self) -> QToolButton | None:
        if not self._item:
            return None
        scopes = available_scopes(self._item, self._workspace_folder)
        if not scopes:
            return None
        btn = self._mk_action_btn(
            "📥  Instalar em…  ▾", "Copia este recurso pra outro escopo",
        )
        # InstantPopup: o botão inteiro abre o menu, sem separador vertical
        # que faz o QPushButton.setMenu() parecer "dois botões grudados"
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for scope, ws_folder, label in scopes:
            act = QAction(label, menu)
            act.triggered.connect(
                lambda _, s=scope, w=ws_folder, lab=label: self._do_install(s, w, lab)
            )
            menu.addAction(act)
        btn.setMenu(menu)
        return btn

    def _do_install(self, scope: str, ws_folder: str | None, label: str) -> None:
        if not self._item:
            return
        try:
            try:
                target = install_item(self._item, scope, ws_folder, overwrite=False)
            except LaunchError as exists_err:
                if "já existe" not in str(exists_err):
                    raise
                resp = QMessageBox.question(
                    self, "Sobrescrever?",
                    f"Já existe em {scope}.\n\nSobrescrever {self._item.name}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if resp != QMessageBox.StandardButton.Yes:
                    return
                target = install_item(self._item, scope, ws_folder, overwrite=True)
        except LaunchError as e:
            QMessageBox.critical(self, "Falha ao instalar", str(e))
            return
        from .persistent_toast import flash_toast
        flash_toast(f"{self._item.name} instalado — reinicie o Claude no workspace")

    def _open_editor(self) -> None:
        if not self._item:
            return
        from .skill_editor_dialog import SkillEditorDialog
        dlg = SkillEditorDialog(self._item, self._catalog_names, parent=self)
        if dlg.exec():
            self._render()  # recarrega após edição

    def _open_playground(self) -> None:
        if not self._item or self._settings is None:
            return
        from .skill_playground_dialog import SkillPlaygroundDialog
        dlg = SkillPlaygroundDialog(
            self._item, self._settings,
            cwd=self._workspace_folder, parent=self,
        )
        dlg.show()

    def _copy_invocation(self) -> None:
        if self._item:
            QGuiApplication.clipboard().setText(self._item.invocation)

    def _usage_summary(self, u: SkillUsage) -> str:
        parts = [
            f"<b>{u.count}</b> uso(s)",
            f"último: <b>{u.last_used_label()}</b>" if u.last_used else "",
        ]
        top = sorted(u.by_workspace.items(), key=lambda kv: -kv[1])[:3]
        if top:
            ws_str = ", ".join(
                f"<code>{w.split('/')[-1]}</code> {n}x" for w, n in top
            )
            parts.append(f"top: {ws_str}")
        return "  ·  ".join(p for p in parts if p)

    def _read_body(self) -> str:
        if not self._item:
            return ""
        try:
            text = self._item.path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Falha lendo %s: %s", self._item.path, e)
            return f"_(erro lendo arquivo: {e})_"
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                return text[end + 4:].lstrip("\n")
        return text

    def _parse_frontmatter(self) -> dict[str, str]:
        if not self._item:
            return {}
        try:
            text = self._item.path.read_text(encoding="utf-8")
        except OSError:
            return {}
        fm, _, _ = _parse_frontmatter_raw(text)
        return fm
