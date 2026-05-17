"""Coordena os terminais embutidos.

Centraliza:
- TerminalAreas por workspace_id (lazy)
- TerminalState (tree_items, activity, inbox, running_counts)
- Spinner timer pra animar os children do tree
- Reminder timer pra reavisar tabs aguardando atenção
- Connections com signals de cada TerminalArea criada

Emite signals pra UI consumir:
- workspace_running_changed(workspace_id, count): badge na sidebar
- tab_activity_changed(workspace_id, tab_id, title, status, working, running)
- tab_removed(tab_id)
- inbox_changed(count): pra atualizar bell badge
- inbox_alert(tab_id, info, is_reminder): notificação nativa — primeiro
  toque (is_reminder=False) ou re-lembrete (is_reminder=True)
- terminal_area_created(workspace_id, area): host adiciona ao QStackedWidget

Não importa Qt além de QObject/Signal/QTimer — sem widgets aqui.
"""

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ...models import Workspace
from ..terminal_area import TerminalArea
from ..terminal_state import TerminalState

log = logging.getLogger(__name__)


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL_MS = 100

# Intervalo entre re-lembretes (default — configurável via setting).
# Cada entrada do inbox que está parada há mais que isso, e não foi
# dismissada/snoozed, dispara um inbox_alert(is_reminder=True).
DEFAULT_REMINDER_INTERVAL_S = 120  # 2 min
REMINDER_TICK_MS = 5000  # checa a cada 5s — barato e responsivo


class TerminalCoordinator(QObject):
    workspace_running_changed = Signal(str, int)
    tab_activity_changed = Signal("qint64", str, str, bool, bool, str)
    # tab_id, title, status, is_working, is_running, workspace_id
    tab_removed = Signal("qint64")
    inbox_changed = Signal(int)
    inbox_alert = Signal("qint64", dict, bool)  # tab_id, info, is_reminder
    spinner_tick = Signal(str)  # current spinner char
    terminal_area_created = Signal(str, object)  # workspace_id, TerminalArea

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._areas: dict[str, TerminalArea] = {}
        self.state = TerminalState()
        self._spinner_frame = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(SPINNER_INTERVAL_MS)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        # Reminder timer só liga enquanto a inbox não está vazia
        self._reminder_interval_s: float = DEFAULT_REMINDER_INTERVAL_S
        self._reminder_enabled: bool = True
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(REMINDER_TICK_MS)
        self._reminder_timer.timeout.connect(self._check_reminders)

    # ---------- Areas ----------

    def get_or_create_area(self, workspace: Workspace) -> TerminalArea:
        area = self._areas.get(workspace.id)
        if area is None:
            area = TerminalArea()
            ws_id = workspace.id
            area.running_count_changed.connect(
                lambda c, wid=ws_id: self._on_running_count_changed(wid, c)
            )
            area.tab_activity_changed.connect(
                lambda tab_id, title, status, working, running, wid=ws_id:
                    self._on_tab_activity(
                        wid, tab_id, title, status, working, running
                    )
            )
            area.tab_removed.connect(self._on_tab_removed)
            area.tabs.currentChanged.connect(
                lambda idx, a=area: self._on_tab_focused(a, idx)
            )
            self._areas[ws_id] = area
            self.terminal_area_created.emit(ws_id, area)
        return area

    def area_for(self, workspace_id: str) -> TerminalArea | None:
        return self._areas.get(workspace_id)

    def cleanup_area(self, workspace_id: str) -> TerminalArea | None:
        area = self._areas.pop(workspace_id, None)
        if area is not None:
            area.close_all()
        # Defensive cleanup: garante que tree_items/activity/inbox de qualquer
        # tab desse workspace caiam fora — mesmo que `close_all` não tenha
        # disparado tab_removed por algum motivo (bug raro mas observado).
        released = self.state.release_workspace(workspace_id)
        for tab_id in released:
            self.tab_removed.emit(tab_id)
        if released:
            self.inbox_changed.emit(len(self.state.inbox))
        return area

    # ---------- Activity ----------

    def _on_running_count_changed(self, workspace_id: str, count: int) -> None:
        self.state.set_running_count(workspace_id, count)
        self.workspace_running_changed.emit(workspace_id, count)

    def _on_tab_activity(
        self,
        workspace_id: str,
        tab_id: int,
        title: str,
        status: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        prev = self.state.activity.get(tab_id, ("", False, title))
        prev_working = prev[1]
        self.state.activity[tab_id] = (status, is_working, title)
        # Garante mapping tab→workspace pra cleanup em bloco se o workspace
        # for deletado (release_workspace) antes do tab fechar normalmente.
        self.state.register_tab(tab_id, workspace_id)

        # Detecção working → idle: adiciona ao inbox
        if prev_working and not is_working and is_running:
            already_present = tab_id in self.state.inbox
            self.state.add_to_inbox(tab_id, {
                "workspace_id": workspace_id,
                "title": title,
                "status": status,
            })
            self.inbox_changed.emit(len(self.state.inbox))
            # Primeira chegada (não bounce de working transiente): emite
            # alerta inicial. Bounces preservam added_at — não realertam.
            if not already_present:
                self.inbox_alert.emit(
                    tab_id, dict(self.state.inbox[tab_id]), False
                )
            if not self._reminder_timer.isActive():
                self._reminder_timer.start()
        elif is_working and tab_id in self.state.inbox:
            self.state.remove_from_inbox(tab_id)
            self.inbox_changed.emit(len(self.state.inbox))
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()
        elif not is_running and tab_id in self.state.inbox:
            self.state.remove_from_inbox(tab_id)
            self.inbox_changed.emit(len(self.state.inbox))
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()

        # Liga/desliga spinner
        if self.state.any_working() and not self._spinner_timer.isActive():
            self._spinner_timer.start()
        elif not self.state.any_working() and self._spinner_timer.isActive():
            self._spinner_timer.stop()

        self.tab_activity_changed.emit(
            tab_id, title, status, is_working, is_running, workspace_id
        )

    def _on_tab_removed(self, tab_id: int) -> None:
        inbox_changed = self.state.release_tab(tab_id)
        if inbox_changed:
            self.inbox_changed.emit(len(self.state.inbox))
        if not self.state.any_working():
            self._spinner_timer.stop()
        if not self.state.inbox and self._reminder_timer.isActive():
            self._reminder_timer.stop()
        self.tab_removed.emit(tab_id)

    def _on_tab_focused(self, area: TerminalArea, idx: int) -> None:
        if idx < 0:
            return
        widget = area.tabs.widget(idx)
        if widget is None:
            return
        tab_id = id(widget)
        if self.state.remove_from_inbox(tab_id):
            self.inbox_changed.emit(len(self.state.inbox))
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()

    # ---------- Inbox helpers ----------

    def inbox_count(self) -> int:
        return len(self.state.inbox)

    def inbox_entries(self) -> dict[int, dict]:
        return dict(self.state.inbox)

    def clear_inbox(self) -> None:
        self.state.clear_inbox()
        self.inbox_changed.emit(0)
        if self._reminder_timer.isActive():
            self._reminder_timer.stop()

    def remove_from_inbox(self, tab_id: int) -> None:
        if self.state.remove_from_inbox(tab_id):
            self.inbox_changed.emit(len(self.state.inbox))
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()

    def dismiss_inbox(self, tab_id: int) -> None:
        """'Já vi, não me lembre' — entrada some do alerta mas continua
        listada no menu até o usuário focar a aba."""
        if self.state.dismiss_inbox(tab_id):
            self.inbox_changed.emit(len(self.state.inbox))

    def snooze_inbox(self, tab_id: int, seconds: float) -> None:
        if self.state.snooze_inbox(tab_id, seconds):
            self.inbox_changed.emit(len(self.state.inbox))

    def set_reminder_interval(self, seconds: float, enabled: bool = True) -> None:
        self._reminder_interval_s = max(15.0, float(seconds))
        self._reminder_enabled = enabled
        if not enabled and self._reminder_timer.isActive():
            self._reminder_timer.stop()
        elif enabled and self.state.inbox and not self._reminder_timer.isActive():
            self._reminder_timer.start()

    # ---------- Reminders ----------

    def _check_reminders(self) -> None:
        if not self._reminder_enabled:
            return
        if not self.state.inbox:
            self._reminder_timer.stop()
            return
        now = time.time()
        for tab_id, info in list(self.state.inbox.items()):
            if info.get("dismissed"):
                continue
            if info.get("snooze_until", 0.0) > now:
                continue
            # Aguarda o intervalo desde o último toque (added_at ou último
            # reminder), o que for mais recente.
            last_event = max(
                float(info.get("added_at", 0.0)),
                float(info.get("last_reminded_at", 0.0)),
            )
            if now - last_event < self._reminder_interval_s:
                continue
            info["last_reminded_at"] = now
            self.inbox_alert.emit(tab_id, dict(info), True)

    # ---------- Spinner ----------

    def current_spinner_char(self) -> str:
        return SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
        self.spinner_tick.emit(self.current_spinner_char())
