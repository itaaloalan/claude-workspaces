import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
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
from ..skills_discovery import (
    KIND_AGENT,
    KIND_COMMAND,
    KIND_SKILL,
    ClaudeItem,
    list_all_items,
)
from ..skills_discovery import KIND_LABEL_MAP as KIND_LABEL
from ..skills_lint import LintIssue, lint_all, summarize_severity
from ..skills_telemetry import SkillUsage, aggregate_usage
from .skill_detail_dialog import SkillDetailDialog

log = logging.getLogger(__name__)

KIND_COLOR = {
    KIND_SKILL: "#6aa9e0",
    KIND_AGENT: "#b08cd6",
    KIND_COMMAND: "#5ac35a",
}


_CHIP_CSS = (
    "QPushButton {"
    "  background: transparent; color: #c8c8c8;"
    "  border: 1px solid #2c2c2c; border-radius: 12px;"
    "  padding: 2px 10px; font-size: 11px;"
    "}"
    "QPushButton:hover { color: #e6e6e6; border-color: #3d6ea8; }"
    "QPushButton:checked {"
    "  background: #3d6ea8; color: #fff; border-color: #3d6ea8;"
    "}"
)


class SkillsPanel(QWidget):
    """Lista skills + agents + commands disponíveis no Claude.
    Filtros por tipo e fonte; click copia a invocação."""

    KIND_FILTER_ALL = "all"
    SOURCE_FILTER_ALL = "all"

    item_selected = Signal(object)  # emite ClaudeItem ao clicar

    def __init__(
        self,
        parent: QWidget | None = None,
        settings=None,
        auto_open_detail: bool = True,
    ) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._settings = settings
        self._auto_open_detail = auto_open_detail
        self._all: list[ClaudeItem] = []
        self._usage: dict[tuple[str, str], SkillUsage] = {}
        self._lint: dict = {}
        self._show_zombies_only: bool = False
        self._show_lint_only: bool = False
        self._kind_filter = self.KIND_FILTER_ALL
        self._source_filter = self.SOURCE_FILTER_ALL

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Chips são criados aqui mas o default check é aplicado depois
        # que _list + _search existirem (senão setChecked dispara _render
        # antes da hora)
        self._kind_chips: list[QPushButton] = []
        self._source_chips: list[QPushButton] = []
        outer.addLayout(self._build_chip_row(
            "Tipo:",
            [
                (self.KIND_FILTER_ALL, "Todos"),
                (KIND_SKILL, "Skills"),
                (KIND_AGENT, "Agentes"),
                (KIND_COMMAND, "Comandos"),
            ],
            self._set_kind_filter,
            self._kind_chips,
        ))
        outer.addLayout(self._build_chip_row(
            "Fonte:",
            [
                (self.SOURCE_FILTER_ALL, "Todas"),
                ("project", "Projeto"),
                ("user", "Global"),
                ("plugin", "Plugin"),
            ],
            self._set_source_filter,
            self._source_chips,
        ))

        # Toggles "saúde": zumbis (sem uso) e issues de lint
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(6)
        self._zombie_toggle = QPushButton("👻 Zumbis")
        self._zombie_toggle.setCheckable(True)
        self._zombie_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zombie_toggle.setStyleSheet(_CHIP_CSS)
        self._zombie_toggle.setToolTip("Só skills/agentes nunca usados (ou usados há +30d)")
        self._zombie_toggle.toggled.connect(self._set_zombies_only)
        toggles_row.addWidget(self._zombie_toggle)
        self._lint_toggle = QPushButton("⚠ Com lint")
        self._lint_toggle.setCheckable(True)
        self._lint_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lint_toggle.setStyleSheet(_CHIP_CSS)
        self._lint_toggle.setToolTip("Só itens com issues de frontmatter/body")
        self._lint_toggle.toggled.connect(self._set_lint_only)
        toggles_row.addWidget(self._lint_toggle)
        toggles_row.addStretch()
        outer.addLayout(toggles_row)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filtrar por texto…")
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
        self._list.itemDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._list, stretch=1)

        footer = QHBoxLayout()
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        footer.addWidget(self._counter)
        footer.addStretch()
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Reescanear")
        refresh_btn.clicked.connect(self.refresh)
        footer.addWidget(refresh_btn)
        outer.addLayout(footer)

        # Marca chip default depois de _list e _search já existirem
        for btn in self._kind_chips:
            if btn.property("filter_key") == self._kind_filter:
                btn.setChecked(True)
                break
        for btn in self._source_chips:
            if btn.property("filter_key") == self._source_filter:
                btn.setChecked(True)
                break
        self.refresh()

    def _build_chip_row(self, label_text, options, slot, registry):
        row = QHBoxLayout()
        row.setSpacing(4)
        lab = QLabel(label_text)
        lab.setStyleSheet("color: #888; font-size: 11px;")
        row.addWidget(lab)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for key, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("filter_key", key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_CHIP_CSS)
            btn.toggled.connect(lambda checked, k=key: slot(k) if checked else None)
            grp.addButton(btn)
            row.addWidget(btn)
            registry.append(btn)
        row.addStretch()
        return row

    def _set_kind_filter(self, value: str) -> None:
        self._kind_filter = value
        self._render()

    def _set_source_filter(self, value: str) -> None:
        self._source_filter = value
        self._render()

    def _set_zombies_only(self, checked: bool) -> None:
        self._show_zombies_only = checked
        self._render()

    def _set_lint_only(self, checked: bool) -> None:
        self._show_lint_only = checked
        self._render()

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def refresh(self) -> None:
        folders = self.workspace.folders if self.workspace else []
        self._all = list_all_items(folders)
        try:
            self._usage = aggregate_usage()
        except Exception:
            log.exception("Falha agregando uso de skills/agents")
            self._usage = {}
        try:
            self._lint = lint_all(self._all)
        except Exception:
            log.exception("Falha rodando lint do catálogo")
            self._lint = {}
        self._render()

    def _usage_for(self, item: ClaudeItem) -> SkillUsage | None:
        return self._usage.get((item.kind, item.name))

    def _matches_source(self, item: ClaudeItem) -> bool:
        if self._source_filter == self.SOURCE_FILTER_ALL:
            return True
        if self._source_filter == "plugin":
            return item.source.startswith("plugin:")
        return item.source == self._source_filter

    def _is_zombie(self, item: ClaudeItem) -> bool:
        if item.kind not in (KIND_SKILL, KIND_AGENT):
            return False
        u = self._usage_for(item)
        return u is None or u.count == 0

    def _render(self) -> None:
        from PySide6.QtGui import QBrush, QColor

        needle = self._search.text().strip().lower()
        # Sort: itens com uso primeiro (count desc), zumbis depois,
        # mas issues de lint puxam pra cima dentro do bucket.
        def sort_key(i: ClaudeItem) -> tuple[int, int, str]:
            u = self._usage_for(i)
            count = u.count if u else 0
            sev = summarize_severity(self._lint.get(i.path, []))
            sev_rank = {"error": -3, "warning": -2, "info": -1, "": 0}[sev]
            return (-count, sev_rank, i.name.lower())

        items = sorted(self._all, key=sort_key)
        self._list.clear()
        shown = 0
        for item in items:
            if self._kind_filter != self.KIND_FILTER_ALL and item.kind != self._kind_filter:
                continue
            if not self._matches_source(item):
                continue
            hay = f"{item.name}\n{item.description}\n{item.source}".lower()
            if needle and needle not in hay:
                continue
            if self._show_zombies_only and not self._is_zombie(item):
                continue
            item_issues: list[LintIssue] = self._lint.get(item.path, [])
            if self._show_lint_only and not item_issues:
                continue
            usage = self._usage_for(item)
            sev = summarize_severity(item_issues)
            lint_prefix = ""
            if sev == "error":
                lint_prefix = "⛔ "
            elif sev == "warning":
                lint_prefix = "⚠ "
            elif sev == "info":
                lint_prefix = "ℹ "
            stats_suffix = ""
            if usage and usage.count > 0:
                stats_suffix = f"  ·  {usage.count} uso(s)"
                ago = usage.last_used_label()
                if ago:
                    stats_suffix += f"  ·  {ago}"
            elif item.kind in (KIND_SKILL, KIND_AGENT):
                stats_suffix = "  ·  👻 zumbi"
            label = (
                f"{lint_prefix}[{KIND_LABEL[item.kind]}]  {item.invocation}"
                f"  ·  {item.source_label}{stats_suffix}"
            )
            if item.description:
                desc = item.description.strip().replace("\n", " ")
                if len(desc) > 120:
                    desc = desc[:119] + "…"
                label += f"\n{desc}"
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, item)
            tooltip_parts = [
                str(item.path),
                "Clique: abrir detalhe · Duplo clique: copiar invocação",
            ]
            if item_issues:
                tooltip_parts.append("")
                tooltip_parts.append(f"Lint ({len(item_issues)} issue(s)):")
                for i in item_issues:
                    tooltip_parts.append(f"  {i.badge()} {i.code} · {i.message}")
            if usage and usage.count > 0:
                ws_breakdown = "\n".join(
                    f"  · {cwd}: {n}x"
                    for cwd, n in sorted(
                        usage.by_workspace.items(), key=lambda kv: -kv[1]
                    )[:5]
                )
                tooltip_parts.append("")
                tooltip_parts.append(
                    f"Usos: {usage.count}\n"
                    f"Último: {usage.last_used_label()}\n"
                    f"Por workspace:\n{ws_breakdown}"
                )
            li.setToolTip("\n".join(tooltip_parts))
            li.setForeground(QBrush(QColor(KIND_COLOR.get(item.kind, "#c8c8c8"))))
            self._list.addItem(li)
            shown += 1
        total = len(self._all)
        if total == 0:
            self._counter.setText("nada encontrado")
        else:
            self._counter.setText(f"{shown}/{total}")

    def _on_click(self, item: QListWidgetItem) -> None:
        """Single click → emite signal + (opcional) abre dialog."""
        ci = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(ci, ClaudeItem):
            return
        self.item_selected.emit(ci)
        if not self._auto_open_detail:
            return
        catalog_names = {i.name for i in self._all}
        usage = self._usage_for(ci)
        ws_folder = (
            self.workspace.folders[0]
            if self.workspace and self.workspace.folders
            else None
        )
        dlg = SkillDetailDialog(
            ci, usage, catalog_names,
            workspace_folder=ws_folder,
            settings=self._settings,
            parent=self,
        )
        dlg.finished.connect(lambda _: self.refresh())
        dlg.show()

    def selected_context(self) -> tuple[set[str], str | None]:
        """Helper pro CatalogView: catalog_names + workspace_folder."""
        catalog_names = {i.name for i in self._all}
        ws_folder = (
            self.workspace.folders[0]
            if self.workspace and self.workspace.folders
            else None
        )
        return catalog_names, ws_folder

    def all_items(self) -> list[ClaudeItem]:
        return list(self._all)

    def lint_for(self, item: ClaudeItem):
        return self._lint.get(item.path, [])

    def _on_double_click(self, item: QListWidgetItem) -> None:
        """Duplo clique → copiar invocação (atalho rápido)."""
        ci = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(ci, ClaudeItem):
            return
        QGuiApplication.clipboard().setText(ci.invocation)
        original = item.text()
        item.setText(f"✓ copiado  {ci.invocation}")
        QTimer.singleShot(1000, lambda i=item, t=original: i.setText(t))
