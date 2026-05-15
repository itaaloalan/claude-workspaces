"""Dialog que pergunta antes de abrir um console do Claude se o usuário
quer criar um git worktree isolado (nova branch) ou rodar direto na
branch atual da pasta primária."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..git_status import get_status
from ..git_worktree import suggest_branch_name, worktree_path_for
from ..models import Workspace


log = logging.getLogger(__name__)


class LaunchClaudeDialog(QDialog):
    """Configurações pra abrir o Claude. Devolve via .result_isolate()
    e .result_branch() quando o usuário confirma."""

    def __init__(self, workspace: Workspace, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.setWindowTitle("Abrir Claude")
        self.resize(560, 260)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        v.addWidget(QLabel(f"<b>Workspace:</b> {workspace.name}"))

        primary = workspace.folders[0] if workspace.folders else ""
        status = get_status(primary) if primary else None
        is_repo = bool(status and status.is_repo)
        if is_repo:
            v.addWidget(QLabel(
                f"<b>Pasta:</b> <code>{primary}</code><br>"
                f"<b>Branch atual:</b> <code>{status.branch}</code>"
            ))
        else:
            v.addWidget(QLabel(
                f"<b>Pasta:</b> <code>{primary or '(sem pasta)'}</code><br>"
                f"<i>(não é um repo git — worktree não disponível)</i>"
            ))

        self.isolate_chk = QCheckBox(
            "Isolar em git worktree (nova branch, working tree separada)"
        )
        self.isolate_chk.setToolTip(
            "Cria um worktree em <pasta-pai>/<repo>.claude/<branch>/ rodando "
            "em paralelo. Útil pra múltiplos consoles trabalharem em features "
            "diferentes sem colidir."
        )
        self.isolate_chk.setEnabled(is_repo)
        v.addWidget(self.isolate_chk)

        form = QFormLayout()
        self.branch_edit = QLineEdit(suggest_branch_name())
        self.branch_edit.setEnabled(False)
        form.addRow("Nova branch:", self.branch_edit)

        self.base_edit = QLineEdit(status.branch if is_repo else "")
        self.base_edit.setEnabled(False)
        form.addRow("Saindo de:", self.base_edit)

        self.path_preview = QLabel("")
        self.path_preview.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.path_preview.setWordWrap(True)
        form.addRow("Path:", self.path_preview)

        v.addLayout(form)

        def _toggle_extra(checked: bool):
            self.branch_edit.setEnabled(checked)
            self.base_edit.setEnabled(checked)
            self._refresh_preview()

        self.isolate_chk.toggled.connect(_toggle_extra)
        self.branch_edit.textChanged.connect(self._refresh_preview)

        v.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Abrir Claude")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self.isolate_chk.isChecked() or not self.workspace.folders:
            self.path_preview.setText("(rodar na pasta primária do workspace)")
            return
        try:
            p = worktree_path_for(self.workspace.folders[0], self.branch_edit.text())
            self.path_preview.setText(str(p))
        except Exception:
            self.path_preview.setText("(path inválido)")

    def result_isolate(self) -> bool:
        return self.isolate_chk.isChecked() and self.isolate_chk.isEnabled()

    def result_branch(self) -> str:
        return self.branch_edit.text().strip()

    def result_base_branch(self) -> str:
        return self.base_edit.text().strip()
