"""Detalhe de uma skill/agent/command: frontmatter parsed, body
markdown renderizado, lint issues, telemetria de uso.

Não-modal — usuário pode abrir múltiplos detalhes simultâneos sem
perder a lista atrás.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..skills_discovery import KIND_LABEL_MAP, ClaudeItem
from ..skills_lint import lint_item
from ..skills_telemetry import SkillUsage

log = logging.getLogger(__name__)


class SkillDetailDialog(QDialog):
    def __init__(
        self,
        item: ClaudeItem,
        usage: SkillUsage | None,
        catalog_names: set[str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{item.kind.title()}: {item.name}")
        self.setModal(False)
        self.resize(720, 640)
        self._item = item

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ---------- Header ----------
        header = QHBoxLayout()
        title = QLabel(f"<h2 style='margin:0;'>{item.invocation}</h2>")
        header.addWidget(title)
        header.addStretch()
        copy_btn = QPushButton(f"📋 Copiar {item.invocation}")
        copy_btn.clicked.connect(self._copy_invocation)
        header.addWidget(copy_btn)
        outer.addLayout(header)

        meta = QLabel(
            f"<span style='color:#888;'>"
            f"<b>{KIND_LABEL_MAP.get(item.kind, item.kind)}</b> · "
            f"fonte: <code>{item.source_label}</code> · "
            f"<code style='color:#6aa9e0;'>{item.path}</code>"
            f"</span>"
        )
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(meta)

        # ---------- Lint ----------
        issues = lint_item(item, catalog_names)
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
            outer.addWidget(box)

        # ---------- Telemetria ----------
        if usage and usage.count > 0:
            stats = QLabel(self._usage_summary(usage))
            stats.setStyleSheet("color: #5ac35a;")
            stats.setWordWrap(True)
            outer.addWidget(stats)
        elif item.kind in {"skill", "agent"}:
            zumbi = QLabel(
                "<span style='color:#909399;'>zumbi · nunca foi usada "
                "(ou Claude nunca decidiu invocar)</span>"
            )
            outer.addWidget(zumbi)

        # ---------- Frontmatter ----------
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
            outer.addWidget(fm_box)

        # ---------- Body (markdown) ----------
        body_box = QGroupBox("Conteúdo")
        body_l = QVBoxLayout(body_box)
        self._body_view = QTextBrowser()
        self._body_view.setOpenExternalLinks(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._body_view.setFont(font)
        self._body_view.setMarkdown(self._read_body())
        body_l.addWidget(self._body_view)
        outer.addWidget(body_box, stretch=1)

        # ---------- Footer ----------
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def _copy_invocation(self) -> None:
        QGuiApplication.clipboard().setText(self._item.invocation)
        self.setWindowTitle(f"✓ copiado: {self._item.invocation}")

    def _usage_summary(self, u: SkillUsage) -> str:
        parts = [
            f"<b>{u.count}</b> uso(s)",
            f"último: <b>{u.last_used_label()}</b>" if u.last_used else "",
        ]
        top = sorted(u.by_workspace.items(), key=lambda kv: -kv[1])[:3]
        if top:
            ws_str = ", ".join(f"<code>{w.split('/')[-1]}</code> {n}x" for w, n in top)
            parts.append(f"top: {ws_str}")
        return "  ·  ".join(p for p in parts if p)

    def _read_body(self) -> str:
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
        try:
            text = self._item.path.read_text(encoding="utf-8")
        except OSError:
            return {}
        from ..skills_lint import _parse_frontmatter_raw
        fm, _, _ = _parse_frontmatter_raw(text)
        return fm
