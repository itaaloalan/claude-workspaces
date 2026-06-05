"""NewWorktreeDialog — cria um git worktree num repo do workspace.

Botão "➕ Criar worktree…" do chip 🌿 e dos menus da sidebar. Escolhe o
repo (workspaces multi-repo), a branch (nova ou existente — detectado
automaticamente) e a base quando a branch é nova. O path segue o padrão
<repo>.claude/<branch-sanitizada> (worktree_path_for).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..git_worktree import (
    add_worktree,
    list_local_branches,
    suggest_branch_name,
    worktree_path_for,
)
from . import theme


class NewWorktreeDialog(QDialog):
    """Cria branch+worktree (ou worktree de branch existente) num repo."""

    def __init__(
        self,
        repo_folders: list[str],
        suggested_branch: str = "",
        branch_prefix: str = "claude",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Criar worktree")
        self.setMinimumWidth(520)
        self._created_path: str = ""
        self._created_branch: str = ""
        self._synced_configs: list[str] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._repo = QComboBox()
        for f in repo_folders:
            self._repo.addItem(Path(f).name, f)
        form.addRow("Repositório:", self._repo)

        self._branch = QLineEdit(
            suggested_branch or suggest_branch_name(branch_prefix)
        )
        self._branch.setToolTip(
            "Branch do worktree. Se já existir localmente, o worktree faz "
            "checkout dela; senão a branch é criada a partir da base abaixo."
        )
        form.addRow("Branch:", self._branch)

        self._base = QComboBox()
        form.addRow("Base (se branch nova):", self._base)

        self._preview = QLabel("")
        self._preview.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px;"
        )
        self._preview.setWordWrap(True)
        form.addRow("Path:", self._preview)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._repo.currentIndexChanged.connect(self._on_repo_changed)
        self._branch.textChanged.connect(self._refresh_preview)
        self._on_repo_changed()

    # ---- estado ------------------------------------------------------------

    def created(self) -> tuple[str, str]:
        """(path, branch) do worktree criado ('' se cancelado/falhou)."""
        return self._created_path, self._created_branch

    def synced_configs(self) -> list[str]:
        """Configs locais copiadas do repo principal pro worktree."""
        return list(self._synced_configs)

    def _on_repo_changed(self) -> None:
        repo = self._repo.currentData() or ""
        self._branches = list_local_branches(repo) if repo else []
        self._base.clear()
        self._base.addItems(self._branches)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        repo = self._repo.currentData() or ""
        branch = self._branch.text().strip()
        if not repo or not branch:
            self._preview.setText("")
            return
        exists = branch in getattr(self, "_branches", [])
        self._base.setEnabled(not exists)
        hint = (
            "(branch existente — checkout em novo worktree)"
            if exists
            else "(branch nova a partir da base)"
        )
        self._preview.setText(f"{worktree_path_for(repo, branch)}  {hint}")

    def _on_accept(self) -> None:
        repo = self._repo.currentData() or ""
        branch = self._branch.text().strip()
        if not repo or not branch:
            QMessageBox.warning(self, "Criar worktree", "Informe a branch.")
            return
        exists = branch in getattr(self, "_branches", [])
        ok, msg, dest = add_worktree(
            repo,
            branch,
            base_branch=(self._base.currentText() or None) if not exists else None,
            create_branch=not exists,
        )
        if not ok:
            QMessageBox.warning(
                self, "Falha ao criar worktree", msg or "erro desconhecido"
            )
            return
        # Configs locais do repo principal (banco, .env…) → worktree.
        try:
            from ..services.worktree_bootstrap import sync_local_configs
            self._synced_configs = sync_local_configs(repo, str(dest))
        except Exception:  # noqa: BLE001 — criação vale mesmo sem a cópia
            self._synced_configs = []
        self._created_path = str(dest)
        self._created_branch = branch
        self.accept()
