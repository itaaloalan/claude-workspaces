"""Editor visual de skill/agent/command com validação live.

Usa o mesmo lint que o catálogo — usuário vê o status enquanto edita.
Salva substituindo o arquivo original (cria backup .bak antes).
"""

import logging
import shutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..skills_discovery import KIND_AGENT, ClaudeItem
from ..skills_lint import (
    SEV_ERROR,
    SEV_WARNING,
    LintIssue,
    _parse_frontmatter_raw,
    lint_item,
)

log = logging.getLogger(__name__)


class SkillEditorDialog(QDialog):
    def __init__(
        self,
        item: ClaudeItem,
        catalog_names: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Editar {item.kind}: {item.name}")
        self.setModal(True)
        self.resize(820, 720)
        self._item = item
        self._catalog_names = catalog_names or set()

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # Header
        header = QLabel(
            f"<b>{item.kind.title()}</b> · "
            f"<code>{item.path}</code>"
        )
        header.setStyleSheet("color: #888;")
        header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(header)

        # Frontmatter form
        fm_box = QGroupBox("Frontmatter")
        fm_l = QVBoxLayout(fm_box)
        fm_l.setSpacing(6)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("nome-em-kebab-case")
        fm_l.addWidget(QLabel("name:"))
        fm_l.addWidget(self._name_edit)

        fm_l.addWidget(QLabel("description:"))
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText(
            "Quando o Claude deve invocar esta skill/agente. "
            "Seja específico sobre triggers (ex: 'Use quando o usuário pedir "
            "para commitar mudanças')."
        )
        self._desc_edit.setMaximumHeight(80)
        fm_l.addWidget(self._desc_edit)

        if item.kind == KIND_AGENT:
            fm_l.addWidget(QLabel("tools (opcional, vírgula):"))
            self._tools_edit = QLineEdit()
            self._tools_edit.setPlaceholderText("Read, Grep, Bash")
            fm_l.addWidget(self._tools_edit)
        else:
            self._tools_edit = None

        # Outras chaves de frontmatter — passthrough raw
        fm_l.addWidget(QLabel("Outras chaves (frontmatter raw extra, opcional):"))
        self._extra_fm = QPlainTextEdit()
        self._extra_fm.setMaximumHeight(60)
        self._extra_fm.setPlaceholderText("model: opus\nallowed-tools: Read")
        fm_l.addWidget(self._extra_fm)

        outer.addWidget(fm_box)

        # Body
        body_box = QGroupBox("Conteúdo (markdown)")
        body_l = QVBoxLayout(body_box)
        self._body_edit = QPlainTextEdit()
        self._body_edit.setPlaceholderText(
            "# Título\n\nInstruções pro Claude…"
        )
        body_l.addWidget(self._body_edit)
        outer.addWidget(body_box, stretch=1)

        # Lint status
        self._lint_status = QLabel()
        self._lint_status.setWordWrap(True)
        self._lint_status.setStyleSheet("color: #5ac35a;")
        outer.addWidget(self._lint_status)

        # Footer
        buttons = QDialogButtonBox()
        self._save_btn = QPushButton("💾 Salvar")
        self._save_btn.clicked.connect(self._save)
        buttons.addButton(self._save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        outer.addWidget(buttons)

        # Debounced relint
        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(300)
        self._lint_timer.timeout.connect(self._relint)
        for w in (self._name_edit, self._desc_edit, self._body_edit, self._extra_fm):
            sig = w.textChanged
            sig.connect(self._lint_timer.start)
        if self._tools_edit:
            self._tools_edit.textChanged.connect(self._lint_timer.start)

        self._load_from_file()
        self._relint()

    # ---------- Load / Save ----------

    def _load_from_file(self) -> None:
        try:
            text = self._item.path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "Erro lendo arquivo", str(e))
            self.reject()
            return
        fm, body, _err = _parse_frontmatter_raw(text)
        self._name_edit.setText(fm.pop("name", "") or self._item.name)
        self._desc_edit.setPlainText(fm.pop("description", "") or "")
        if self._tools_edit:
            self._tools_edit.setText(fm.pop("tools", "") or "")
        # Outras chaves restantes
        extras = "\n".join(f"{k}: {v}" for k, v in fm.items())
        self._extra_fm.setPlainText(extras)
        self._body_edit.setPlainText(body)

    def _compose_frontmatter(self) -> str:
        lines: list[str] = []
        name = self._name_edit.text().strip()
        if name:
            lines.append(f"name: {name}")
        desc = self._desc_edit.toPlainText().strip()
        if desc:
            lines.append(f"description: {desc}")
        if self._tools_edit:
            tools = self._tools_edit.text().strip()
            if tools:
                lines.append(f"tools: {tools}")
        extras_raw = self._extra_fm.toPlainText().strip()
        if extras_raw:
            lines.append(extras_raw)
        return "\n".join(lines)

    def _compose_full(self) -> str:
        fm = self._compose_frontmatter()
        body = self._body_edit.toPlainText()
        if fm:
            return f"---\n{fm}\n---\n\n{body}".rstrip() + "\n"
        return body

    # ---------- Lint ----------

    def _relint(self) -> None:
        # Cria um ClaudeItem virtual baseado no path original, mas rodando
        # lint contra o conteúdo recém-composto via um arquivo temporário
        # in-memory wouldn't work com lint_item que lê do disco, então:
        # tempfile leve.
        import tempfile
        full = self._compose_full()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fp:
            fp.write(full)
            tmp_path = fp.name
        try:
            from pathlib import Path
            virtual_item = ClaudeItem(
                name=self._name_edit.text() or self._item.name,
                description=self._desc_edit.toPlainText(),
                source=self._item.source,
                kind=self._item.kind,
                path=Path(tmp_path),
            )
            issues = lint_item(virtual_item, self._catalog_names)
        finally:
            try:
                from pathlib import Path
                Path(tmp_path).unlink()
            except OSError:
                pass
        self._update_lint_display(issues)

    def _update_lint_display(self, issues: list[LintIssue]) -> None:
        if not issues:
            self._lint_status.setText("✓ Sem issues de lint")
            self._lint_status.setStyleSheet("color: #5ac35a;")
            self._save_btn.setEnabled(True)
            return
        has_error = any(i.severity == SEV_ERROR for i in issues)
        parts = []
        for i in issues:
            color = (
                "#e74c3c" if i.severity == SEV_ERROR
                else "#e6a23c" if i.severity == SEV_WARNING
                else "#909399"
            )
            parts.append(
                f"<span style='color:{color};'>{i.badge()} {i.code}</span> {i.message}"
            )
        self._lint_status.setText(" · ".join(parts))
        self._lint_status.setStyleSheet("")  # cores inline
        # Permite salvar com warnings, bloqueia com errors
        self._save_btn.setEnabled(not has_error)
        if has_error:
            self._save_btn.setToolTip("Resolva os erros antes de salvar")
        else:
            self._save_btn.setToolTip("")

    # ---------- Save ----------

    def _save(self) -> None:
        new_text = self._compose_full()
        # Backup curto antes de sobrescrever
        try:
            shutil.copy2(self._item.path, self._item.path.with_suffix(
                self._item.path.suffix + ".bak"
            ))
        except OSError as e:
            log.warning("Falha criando backup de %s: %s", self._item.path, e)
        try:
            self._item.path.write_text(new_text, encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "Erro salvando", str(e))
            return
        log.info("Skill/agent salvo: %s", self._item.path)
        QMessageBox.information(
            self, "Salvo",
            f"Conteúdo gravado em:\n{self._item.path}\n\n"
            f"Backup: {self._item.path.with_suffix(self._item.path.suffix + '.bak')}",
        )
        self.accept()
