from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Workspace
from ..skills_discovery import Skill, list_all_skills


class SkillsPanel(QWidget):
    """Lista as skills disponíveis no Claude Code com busca + click pra copiar
    a invocação (/name) na área de transferência."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._all: list[Skill] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar skills…")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 4px 8px; color: #e6e6e6; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._search.textChanged.connect(self._render)
        outer.addWidget(self._search)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QListWidget::item {"
            "  padding: 6px 8px; border-bottom: 1px solid #232323;"
            "  color: #d0d0d0;"
            "}"
            "QListWidget::item:hover { background: #2a3142; color: #fff; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._list.setWordWrap(True)
        self._list.itemClicked.connect(self._on_click)
        outer.addWidget(self._list, stretch=1)

        footer = QHBoxLayout()
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        footer.addWidget(self._counter)
        footer.addStretch()
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Reescanear ~/.claude/skills, plugins e projeto")
        refresh_btn.clicked.connect(self.refresh)
        footer.addWidget(refresh_btn)
        outer.addLayout(footer)

        self.refresh()

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def refresh(self) -> None:
        folders = self.workspace.folders if self.workspace else []
        self._all = list_all_skills(folders)
        self._render()

    def _render(self) -> None:
        needle = self._search.text().strip().lower()
        self._list.clear()
        shown = 0
        for s in self._all:
            hay = f"{s.name}\n{s.description}\n{s.source}".lower()
            if needle and needle not in hay:
                continue
            label = f"/{s.name}  ·  {s.source_label}"
            if s.description:
                # Truncate longa
                desc = s.description.strip().replace("\n", " ")
                if len(desc) > 120:
                    desc = desc[:119] + "…"
                label += f"\n{desc}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s)
            item.setToolTip(f"{s.path}\n\nClique pra copiar  {s.invocation}")
            self._list.addItem(item)
            shown += 1
        total = len(self._all)
        if total == 0:
            self._counter.setText("nenhuma skill encontrada")
        else:
            self._counter.setText(f"{shown}/{total} skills")

    def _on_click(self, item: QListWidgetItem) -> None:
        skill = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(skill, Skill):
            return
        QGuiApplication.clipboard().setText(skill.invocation)
        original = item.text()
        item.setText(f"✓ copiado  {skill.invocation}")
        QTimer.singleShot(1000, lambda i=item, t=original: i.setText(t))
