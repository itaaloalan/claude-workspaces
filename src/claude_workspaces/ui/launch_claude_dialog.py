"""Dialog que pergunta antes de abrir um console do Claude:
- quais pastas do workspace incluir (cwd + --add-dir)
- se quer criar um git worktree isolado
- e nele: criar nova branch OU usar uma branch existente."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QStyle,
    QVBoxLayout,
)


def _white_standard_icon(style: QStyle, sp: QStyle.StandardPixmap, size: int = 16) -> QIcon:
    pm = style.standardIcon(sp).pixmap(size, size)
    if pm.isNull():
        return QIcon()
    tinted = QPixmap(pm.size())
    tinted.fill(Qt.GlobalColor.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), QColor("white"))
    p.end()
    return QIcon(tinted)

from ..git_status import get_status
from ..git_worktree import (
    list_local_branches,
    suggest_branch_name,
    worktree_path_for,
)
from ..models import Workspace
from ..settings import Settings

log = logging.getLogger(__name__)


class LaunchClaudeDialog(QDialog):
    """Configurações pra abrir o Claude embutido.

    Acessores públicos:
    - result_folders()      -> [path, ...]   (cwd = primeiro)
    - result_isolate()      -> bool
    - result_create_branch()-> bool          (só relevante se isolate)
    - result_branch()       -> str           (nome da nova branch OU branch existente)
    - result_base_branch()  -> str           (só quando create_branch True)
    """

    def __init__(self, workspace: Workspace, settings: Settings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.settings = settings or Settings()
        self.setWindowTitle("Abrir Claude")
        self.resize(560, 420)

        v = QVBoxLayout(self)
        v.setSpacing(6)
        v.setContentsMargins(12, 10, 12, 10)

        header = QLabel(
            f"<b>Workspace:</b> {workspace.name} &nbsp;·&nbsp; "
            f"<span style='color:#b0b0b0;'>1ª pasta = cwd, demais como "
            f"<code>--add-dir</code></span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(header)

        self._folder_checks: list[tuple[QCheckBox, str]] = []
        for folder in workspace.folders:
            cb = QCheckBox(folder)
            cb.setChecked(True)
            cb.toggled.connect(self._refresh_preview)
            v.addWidget(cb)
            self._folder_checks.append((cb, folder))

        if not workspace.folders:
            empty = QLabel("(workspace sem pastas — edite antes de abrir)")
            empty.setStyleSheet("color: #d57272;")
            v.addWidget(empty)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        v.addWidget(sep)

        # ---------- Git ----------
        primary = workspace.folders[0] if workspace.folders else None
        status = get_status(primary) if primary else None
        self._is_repo = bool(status and status.is_repo)
        self._current_branch = status.branch if self._is_repo else ""
        self._branches: list[str] = (
            list_local_branches(primary) if self._is_repo else []
        )

        if self._is_repo:
            git_hdr = QLabel(
                f"<b>Git:</b> branch atual <code>{self._current_branch}</code>"
            )
        else:
            git_hdr = QLabel(
                "<b>Git:</b> <span style='color:#b0b0b0;'>"
                "pasta primária não é repo — worktree indisponível</span>"
            )
        v.addWidget(git_hdr)

        # Defaults: workspace override > settings
        isolate_default = (
            workspace.default_isolate_worktree
            if workspace.default_isolate_worktree is not None
            else self.settings.default_isolate_worktree
        )
        create_branch_default = (
            workspace.default_create_new_branch
            if workspace.default_create_new_branch is not None
            else self.settings.default_create_new_branch
        )
        prefix = workspace.branch_prefix or self.settings.branch_prefix

        self.isolate_chk = QCheckBox(
            "Isolar em git worktree (working tree separada)"
        )
        self.isolate_chk.setEnabled(self._is_repo)
        if self._is_repo and isolate_default:
            self.isolate_chk.setChecked(True)
        v.addWidget(self.isolate_chk)

        self.new_branch_chk = QCheckBox("Criar nova branch")
        self.new_branch_chk.setChecked(create_branch_default)
        # Sempre disponível quando há repo (independente de worktree).
        # Quando isolate=False + new_branch=True: roda git checkout -b
        # no cwd antes de iniciar Claude. Quando isolate=True: usado pelo
        # worktree.
        self.new_branch_chk.setEnabled(self._is_repo)
        v.addWidget(self.new_branch_chk)

        form = QFormLayout()
        self.branch_edit = QLineEdit(suggest_branch_name(prefix))
        self.branch_edit.setEnabled(False)
        form.addRow("Nome da nova branch:", self.branch_edit)

        # "Saindo de" — text edit (base pra nova branch)
        self.base_edit = QLineEdit(self._current_branch)
        self.base_edit.setEnabled(False)
        form.addRow("Saindo de:", self.base_edit)

        # "Branch existente" — combo
        self.existing_combo = QComboBox()
        if self._branches:
            self.existing_combo.addItems(self._branches)
            # Default = current branch
            if self._current_branch in self._branches:
                self.existing_combo.setCurrentText(self._current_branch)
        self.existing_combo.setEnabled(False)
        form.addRow("Branch existente:", self.existing_combo)

        self.path_preview = QLabel("")
        self.path_preview.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        self.path_preview.setWordWrap(True)
        form.addRow("Path:", self.path_preview)

        v.addLayout(form)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #2a2a2a;")
        v.addWidget(sep2)

        prompt_label = QLabel(
            "<b>Prompt inicial</b> "
            "<span style='color:#b0b0b0;'>(opcional — enviado ao iniciar)</span>"
        )
        v.addWidget(prompt_label)
        self.initial_prompt_edit = QPlainTextEdit()
        self.initial_prompt_edit.setPlaceholderText(
            "Ex.: revise o arquivo X e proponha melhorias…"
        )
        self.initial_prompt_edit.setFixedHeight(64)
        v.addWidget(self.initial_prompt_edit)

        # Wiring
        self.isolate_chk.toggled.connect(self._on_isolate_toggled)
        self.new_branch_chk.toggled.connect(self._on_new_branch_toggled)
        self.branch_edit.textChanged.connect(self._refresh_preview)
        self.existing_combo.currentTextChanged.connect(self._refresh_preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        style = self.style()
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Abrir Claude")
        ok_btn.setIcon(_white_standard_icon(style, QStyle.StandardPixmap.SP_DialogOkButton))
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setIcon(_white_standard_icon(style, QStyle.StandardPixmap.SP_DialogCancelButton))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._sync_enabled_states()
        self._refresh_preview()

    def _on_isolate_toggled(self, checked: bool) -> None:
        self.new_branch_chk.setEnabled(checked and self._is_repo)
        self._sync_enabled_states()
        self._refresh_preview()

    def _on_new_branch_toggled(self, _checked: bool) -> None:
        self._sync_enabled_states()
        self._refresh_preview()

    def _sync_enabled_states(self) -> None:
        isolating = self.isolate_chk.isChecked() and self._is_repo
        new_branch = self.new_branch_chk.isChecked()
        # new_branch_chk: sempre disponível em repo (mesmo sem worktree)
        self.new_branch_chk.setEnabled(self._is_repo)
        # branch_edit + base_edit: relevantes quando create_branch=True
        self.branch_edit.setEnabled(self._is_repo and new_branch)
        self.base_edit.setEnabled(self._is_repo and new_branch)
        # existing_combo: só faz sentido em worktree (sem isolate, ficamos
        # na branch atual; o combo não muda nada)
        self.existing_combo.setEnabled(isolating and not new_branch)

    def _refresh_preview(self) -> None:
        folders = self.result_folders()
        self._ok_btn.setEnabled(bool(folders))
        if not self.isolate_chk.isChecked() or not folders:
            self.path_preview.setText("(rodar na pasta primária marcada, sem worktree)")
            return
        try:
            branch = self.result_branch()
            p = worktree_path_for(folders[0], branch)
            self.path_preview.setText(str(p))
        except Exception:
            log.debug("path preview falhou", exc_info=True)
            self.path_preview.setText("(path inválido)")

    # ---------- API pública ----------

    def result_folders(self) -> list[str]:
        return [f for cb, f in self._folder_checks if cb.isChecked()]

    def result_isolate(self) -> bool:
        return self.isolate_chk.isChecked() and self._is_repo

    def result_create_branch(self) -> bool:
        return self.new_branch_chk.isChecked()

    def result_branch(self) -> str:
        if self.new_branch_chk.isChecked():
            return self.branch_edit.text().strip()
        return self.existing_combo.currentText().strip()

    def result_base_branch(self) -> str:
        return self.base_edit.text().strip()

    def result_initial_prompt(self) -> str:
        return self.initial_prompt_edit.toPlainText().strip()
