"""Dialog para gerar runner com Claude ou retomar geração anterior.

Substitui o `QInputDialog.getText` simples por uma UI com:
  - campo de hint pra nova geração;
  - lista das sessões anteriores de runner-gen deste workspace
    (persistidas em `services/runner_gen_history.py`);
  - filtro por substring na lista;
  - botões "Retomar selecionada" e "Esquecer" (remove do índice).
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..services.runner_gen_history import (
    RunnerGenEntry,
    entries_for_workspace,
    remove_entry,
)


class RunnerGenDialog(QDialog):
    """Resultado: `mode()` ∈ {"new", "resume", None} e `hint()` / `selected_entry()`."""

    def __init__(self, workspace_id: str, workspace_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gerar runner com Claude")
        self.resize(640, 520)

        self._workspace_id = workspace_id
        self._mode: str | None = None
        self._selected: RunnerGenEntry | None = None

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel(f"Workspace: <b>{workspace_name}</b>"))

        root.addWidget(QLabel("Hint pra nova geração (opcional):"))
        self._hint = QLineEdit()
        self._hint.setPlaceholderText("ex: 'web em next', 'glassfish do ogpms'")
        self._hint.returnPressed.connect(self._on_generate_new)
        root.addWidget(self._hint)

        root.addSpacing(6)
        sep_row = QHBoxLayout()
        sep_row.addWidget(QLabel("<b>Sessões anteriores</b>"))
        sep_row.addStretch(1)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("filtrar por texto…")
        self._filter.setClearButtonEnabled(True)
        self._filter.setMaximumWidth(220)
        self._filter.textChanged.connect(self._apply_filter)
        sep_row.addWidget(self._filter)
        root.addLayout(sep_row)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _i: self._on_resume_selected())
        self._list.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self._list, stretch=1)

        self._empty_label = QLabel(
            "(sem sessões anteriores neste workspace — gere uma nova abaixo)"
        )
        self._empty_label.setStyleSheet("color: #888; font-size: 11px;")
        root.addWidget(self._empty_label)

        actions = QHBoxLayout()
        self._resume_btn = QPushButton("↻ Retomar selecionada")
        self._resume_btn.clicked.connect(self._on_resume_selected)
        actions.addWidget(self._resume_btn)
        self._forget_btn = QPushButton("Esquecer")
        self._forget_btn.setToolTip("Remove a entrada do índice (não apaga o JSONL no disco).")
        self._forget_btn.clicked.connect(self._on_forget_selected)
        actions.addWidget(self._forget_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        bb = QDialogButtonBox()
        self._gen_btn = bb.addButton("Gerar nova", QDialogButtonBox.ButtonRole.AcceptRole)
        self._gen_btn.clicked.connect(self._on_generate_new)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        root.addWidget(bb)

        self._reload()

    def _reload(self) -> None:
        self._all_entries = entries_for_workspace(self._workspace_id)
        self._render(self._all_entries)

    def _render(self, entries: list[RunnerGenEntry]) -> None:
        self._list.clear()
        for e in entries:
            label = self._format_entry(e)
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, e)
            if not e.exists_on_disk():
                li.setForeground(Qt.GlobalColor.gray)
                li.setToolTip(
                    f"JSONL não encontrado em ~/.claude/projects — não dá pra retomar.\n"
                    f"session_id: {e.session_id}\ncwd: {e.cwd}"
                )
            else:
                li.setToolTip(
                    f"session_id: {e.session_id}\ncwd: {e.cwd}\nem {e.created_at}"
                )
            self._list.addItem(li)
        self._empty_label.setVisible(self._list.count() == 0)
        self._update_buttons()

    def _format_entry(self, e: RunnerGenEntry) -> str:
        when = self._fmt_when(e.created_at)
        hint = e.hint.strip() or "(sem hint)"
        return f"{when}  ·  {hint}"

    def _fmt_when(self, iso: str) -> str:
        try:
            dt = datetime.fromisoformat(iso)
            return dt.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return iso or "?"

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        if not text:
            self._render(self._all_entries)
            return
        filtered = [
            e for e in self._all_entries
            if text in e.hint.lower() or text in e.session_id.lower()
        ]
        self._render(filtered)

    def _update_buttons(self) -> None:
        sel = self._current_entry()
        has_sel = sel is not None
        can_resume = bool(sel and sel.exists_on_disk())
        self._resume_btn.setEnabled(can_resume)
        self._forget_btn.setEnabled(has_sel)

    def _current_entry(self) -> RunnerGenEntry | None:
        items = self._list.selectedItems()
        if not items:
            return None
        e = items[0].data(Qt.ItemDataRole.UserRole)
        return e if isinstance(e, RunnerGenEntry) else None

    def _on_generate_new(self) -> None:
        self._mode = "new"
        self.accept()

    def _on_resume_selected(self) -> None:
        e = self._current_entry()
        if e is None or not e.exists_on_disk():
            return
        self._mode = "resume"
        self._selected = e
        self.accept()

    def _on_forget_selected(self) -> None:
        e = self._current_entry()
        if e is None:
            return
        remove_entry(e.session_id)
        self._reload()

    def mode(self) -> str | None:
        return self._mode

    def hint(self) -> str:
        return self._hint.text().strip()

    def selected_entry(self) -> RunnerGenEntry | None:
        return self._selected
