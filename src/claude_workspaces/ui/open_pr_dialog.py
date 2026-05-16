"""Dialog pra revisar e abrir Pull Request no GitHub.

Recebe título e body pré-montados (via `pr_draft.build_draft_for_folder`)
e devolve os valores editados via `.values()`. A execução do `gh` fica no
caller — assim o dialog é puramente apresentacional."""

import logging

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

log = logging.getLogger(__name__)


class OpenPullRequestDialog(QDialog):
    def __init__(
        self,
        repo_label: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Abrir Pull Request")
        self.resize(760, 600)

        v = QVBoxLayout(self)
        v.setSpacing(8)

        head = QLabel(
            f"Repo: <b>{repo_label}</b>  ·  "
            f"<b>{branch}</b> → <b>{base}</b>"
        )
        head.setStyleSheet("color: #c8c8c8;")
        v.addWidget(head)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self._title = QLineEdit(title)
        self._title.setStyleSheet(self._INPUT_CSS)
        form.addRow("Título:", self._title)
        self._base = QLineEdit(base)
        self._base.setStyleSheet(self._INPUT_CSS)
        form.addRow("Base:", self._base)
        v.addLayout(form)

        v.addWidget(QLabel("Corpo (Markdown):"))
        self._body = QPlainTextEdit(body)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._body.setFont(mono)
        self._body.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6; padding: 8px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        v.addWidget(self._body, stretch=1)

        self._draft = QCheckBox("Abrir como draft")
        v.addWidget(self._draft)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Abrir PR")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    _INPUT_CSS = (
        "QLineEdit {"
        "  background: #181818; border: 1px solid #2c2c2c;"
        "  border-radius: 4px; color: #e6e6e6; padding: 4px 6px;"
        "}"
        "QLineEdit:focus { border-color: #3d6ea8; }"
    )

    def values(self) -> tuple[str, str, str, bool]:
        """Devolve (title, base, body, draft) após o usuário confirmar."""
        return (
            self._title.text().strip(),
            self._base.text().strip(),
            self._body.toPlainText().rstrip(),
            self._draft.isChecked(),
        )
