"""Dialog de busca de texto livre nas sessões do Claude.

Atalho: Ctrl+Shift+F. Faz substring através de TODOS os JSONLs
em ~/.claude/projects/, filtra por data, mostra resultados ordenados
por recência. Click num resultado emite session_chosen(SearchHit).
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..sessions_search import SearchHit, search_sessions

log = logging.getLogger(__name__)


PERIODS = [
    ("Tudo", None),
    ("Hoje", timedelta(days=1)),
    ("Última semana", timedelta(days=7)),
    ("Último mês", timedelta(days=30)),
    ("Últimos 3 meses", timedelta(days=90)),
]


class SessionsSearchDialog(QDialog):
    session_chosen = Signal(SearchHit)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buscar nas sessões")
        self.resize(820, 560)

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # Linha de busca + período
        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar texto nas conversas com o Claude…")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(
            "QLineEdit { background: #1f1f1f; border: 1px solid #2c2c2c; "
            "border-radius: 4px; padding: 6px 10px; color: #e6e6e6; }"
            "QLineEdit:focus { border-color: #3d6ea8; }"
        )
        self._search.textChanged.connect(self._schedule_search)
        self._search.returnPressed.connect(self._search_now)
        top.addWidget(self._search, stretch=1)

        self._period = QComboBox()
        for label, _ in PERIODS:
            self._period.addItem(label)
        self._period.setCurrentIndex(2)  # default: última semana
        self._period.currentIndexChanged.connect(self._schedule_search)
        top.addWidget(self._period)

        v.addLayout(top)

        self._status = QLabel("Digite pra buscar.")
        self._status.setStyleSheet("color: #b0b0b0; font-size: 11px;")
        v.addWidget(self._status)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.setStyleSheet(
            "QListWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QListWidget::item {"
            "  padding: 8px 10px; border-bottom: 1px solid #232323;"
            "}"
            "QListWidget::item:hover { background: #2a3142; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemDoubleClicked.connect(self._on_activated)
        v.addWidget(self._list, stretch=1)

        # Timer pra debounce digitação
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._search_now)

    def _schedule_search(self, *_args) -> None:
        self._search_timer.start()

    def _search_now(self) -> None:
        query = self._search.text().strip()
        if len(query) < 2:
            self._list.clear()
            self._status.setText("(digite ao menos 2 caracteres)")
            return
        # Periodo
        idx = self._period.currentIndex()
        _, delta = PERIODS[idx]
        since = (
            datetime.now(UTC) - delta if delta else None
        )
        self._status.setText("buscando…")
        QTimer.singleShot(0, lambda: self._do_search(query, since))

    def _do_search(self, query: str, since: datetime | None) -> None:
        try:
            hits = search_sessions(query, since=since)
        except Exception as e:
            log.exception("erro na busca")
            self._status.setText(f"erro: {e}")
            return
        self._render(hits)

    def _render(self, hits: list[SearchHit]) -> None:
        self._list.clear()
        if not hits:
            self._status.setText("0 resultados")
            return
        self._status.setText(f"{len(hits)} resultado(s) (mais recentes primeiro)")
        for h in hits:
            label_top = h.label()
            ts = h.last_modified.astimezone()
            when = ts.strftime("%d/%m/%Y %H:%M")
            proj_name = Path(h.project_path).name or h.project_path
            label = (
                f"{label_top}\n"
                f"  {when}  ·  {proj_name}  ·  {h.match_count} match(es)"
            )
            if h.snippet:
                label += f"\n  {h.snippet}"
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, h)
            li.setToolTip(
                f"Session: {h.session_id}\n"
                f"Arquivo: {h.file_path}\n"
                f"Cwd: {h.project_path}"
            )
            self._list.addItem(li)

    def _on_activated(self, item: QListWidgetItem) -> None:
        hit = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(hit, SearchHit):
            self.session_chosen.emit(hit)
            self.accept()
