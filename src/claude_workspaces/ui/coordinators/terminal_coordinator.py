"""Coordena os terminais embutidos.

Centraliza:
- TerminalAreas por workspace_id (lazy)
- TerminalState (tree_items, activity, inbox, running_counts)
- Spinner timer pra animar os children do tree
- Reminder timer pra reavisar tabs aguardando atenção
- Connections com signals de cada TerminalArea criada

Emite signals pra UI consumir:
- workspace_running_changed(workspace_id, count): badge na sidebar
- tab_activity_changed(tab_id, title, status, working, running, workspace_id, needs_decision)
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
from ..spinner import SPINNER_FRAMES, SPINNER_INTERVAL_MS
from ..terminal_area import TerminalArea
from ..terminal_state import TerminalState
from ..terminal_widget import tab_uid_of

log = logging.getLogger(__name__)


__all__ = ["SPINNER_FRAMES", "SPINNER_INTERVAL_MS", "TerminalCoordinator"]

# Intervalo entre re-lembretes (default — configurável via setting).
# Cada entrada do inbox que está parada há mais que isso, e não foi
# dismissada/snoozed, dispara um inbox_alert(is_reminder=True).
DEFAULT_REMINDER_INTERVAL_S = 120  # 2 min
REMINDER_TICK_MS = 5000  # checa a cada 5s — barato e responsivo


class TerminalCoordinator(QObject):
    workspace_running_changed = Signal(str, int)
    tab_activity_changed = Signal("qint64", str, str, bool, bool, str, bool)
    # tab_id, title, status, is_working, is_running, workspace_id, needs_decision
    tab_removed = Signal("qint64")
    inbox_changed = Signal(int)
    inbox_alert = Signal("qint64", dict, bool)  # tab_id, info, is_reminder
    # Tab ENTROU em is_working (idle/awaiting → working). MainWindow usa pra
    # mostrar/atualizar a notificação fixa "Trabalhando" (que depois vira
    # Aguardando/Pronto na mesma entrada via dedup compartilhado).
    agent_working = Signal("qint64", dict)  # tab_id, info
    # Tab SAIU de is_working. MainWindow fecha a notif "Trabalhando" se nada
    # (Aguardando/Decisão) a substituiu — ex.: trabalho-relâmpago < 1.5s, ou o
    # alerta de "Pronto" foi suprimido porque o console estava em foco.
    agent_working_ended = Signal("qint64", dict)  # tab_id, info
    # Emitido sempre que um tab deixa o inbox (por qualquer motivo: voltou
    # a trabalhar, terminou, foi removido, foco do usuário, dismiss). O
    # MainWindow usa pra fechar a notificação D-Bus correspondente antes
    # do timeout, evitando banner stale na tela.
    inbox_entry_removed = Signal("qint64")  # tab_id
    spinner_tick = Signal(str)  # current spinner char
    terminal_area_created = Signal(str, object)  # workspace_id, TerminalArea
    # Sessão PTY terminou (process exit). exit_code: 0=success, >0=fail,
    # -1=desconhecido. workspace_id pra contextualizar a notif.
    tab_session_exited = Signal("qint64", int, str)  # tab_id, exit_code, workspace_id

    # Duração mínima (segundos) que um tab precisa ficar em is_working=True
    # antes da transição pra is_working=False contar como "Pronto". Filtra
    # flicker de startup do TUI do Claude. Class attr pra testes poderem
    # zerar e ainda validar a transição síncrona.
    _MIN_WORKING_DURATION_S = 1.5

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
        # Estado prévio de needs_decision por tab — usado pra detectar a
        # transição idle→awaiting que também merece alerta nativo
        # (`_on_tab_activity`). Separado de `state.activity` pra não
        # mudar o formato da tupla (status, is_working, title).
        self._prev_needs_decision: dict[int, bool] = {}
        # Timestamp monotônico de quando cada tab entrou em is_working=True.
        # Usado pra filtrar flicker de startup: na primeira renderização do
        # TUI do Claude (welcome banner) o parser cai no fallback "recent &&
        # !looks_prompt" → vira working brevemente, e quando o output dá uma
        # pausa volta pra idle. Sem esse filtro, o working→idle fake dispara
        # "✅ Pronto" assim que o terminal abre. Turnos reais do Claude
        # duram bem mais que esse threshold.
        self._working_started_at: dict[int, float] = {}

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
                lambda tab_id, title, status, working, running, needs_decision, wid=ws_id:
                    self._on_tab_activity(
                        wid, tab_id, title, status, working, running, needs_decision
                    )
            )
            area.tab_removed.connect(self._on_tab_removed)
            area.tab_session_exited.connect(
                lambda tab_id, code, wid=ws_id:
                    self.tab_session_exited.emit(tab_id, code, wid)
            )
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
        inbox_before = set(self.state.inbox.keys())
        released = self.state.release_workspace(workspace_id)
        for tab_id in released:
            self._prev_needs_decision.pop(tab_id, None)
            self._working_started_at.pop(tab_id, None)
            self.tab_removed.emit(tab_id)
            if tab_id in inbox_before:
                self.inbox_entry_removed.emit(tab_id)
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
        needs_decision: bool = False,
    ) -> None:
        prev = self.state.activity.get(tab_id, ("", False, title))
        prev_working = prev[1]
        prev_needs_decision = self._prev_needs_decision.get(tab_id, False)
        self.state.activity[tab_id] = (status, is_working, title)
        self._prev_needs_decision[tab_id] = needs_decision
        # Garante mapping tab→workspace pra cleanup em bloco se o workspace
        # for deletado (release_workspace) antes do tab fechar normalmente.
        self.state.register_tab(tab_id, workspace_id)

        # Adiciona ao inbox em duas transições que merecem atenção:
        #   1) working → not-working (Claude terminou um turno)
        #   2) not-awaiting → awaiting (Claude pediu uma decisão — pode
        #      vir direto de idle quando o picker aparece tão rápido que
        #      o parser não pega o frame de working)
        # Why: antes só (1) disparava notificação nativa, então pickers
        # que apareciam saindo de idle ficavam mudos.
        entered_decision = needs_decision and not prev_needs_decision
        ended_working = prev_working and not is_working
        if ended_working:
            self.agent_working_ended.emit(tab_id, {"workspace_id": workspace_id})
        # Filtra flicker de startup: só conta como working→idle de verdade
        # se o tab ficou em working por pelo menos _MIN_WORKING_DURATION_S.
        import time as _time
        if is_working and not prev_working:
            self._working_started_at[tab_id] = _time.monotonic()
            if is_running:
                # Notificação fixa "Trabalhando" — vira Aguardando/Pronto na
                # mesma entrada quando o trabalho terminar (dedup compartilhado
                # no MainWindow).
                self.agent_working.emit(tab_id, {
                    "workspace_id": workspace_id,
                    "title": title,
                    "status": status,
                })
        ended_working_real = False
        if ended_working:
            started = self._working_started_at.pop(tab_id, None)
            if started is not None and _time.monotonic() - started >= type(self)._MIN_WORKING_DURATION_S:
                ended_working_real = True
        if (ended_working_real or entered_decision) and is_running:
            already_present = tab_id in self.state.inbox
            # `kind` diferencia "Claude terminou um turno" (ready) de
            # "Claude abriu picker/permission prompt" (decision). MainWindow
            # usa pra escolher o prefixo do título da notificação — sem
            # isso, picker abrindo aparecia como "✅ Pronto", o que é
            # enganoso porque Claude não terminou, está perguntando.
            kind = "decision" if entered_decision else "ready"
            self.state.add_to_inbox(tab_id, {
                "workspace_id": workspace_id,
                "title": title,
                "status": status,
                "kind": kind,
            })
            self.inbox_changed.emit(len(self.state.inbox))
            # Primeira chegada (não bounce de working transiente): emite
            # alerta inicial. Bounces preservam added_at — não realertam.
            # Decisões sempre alertam, mesmo que o tab já esteja no inbox
            # como "Pronto" — sem isso um picker aparecendo num console
            # já "Pronto" (usuário não respondeu ainda) ficava mudo.
            if not already_present or entered_decision:
                self.inbox_alert.emit(
                    tab_id, dict(self.state.inbox[tab_id]), False
                )
            if not self._reminder_timer.isActive():
                self._reminder_timer.start()
        elif is_working and tab_id in self.state.inbox:
            self.state.remove_from_inbox(tab_id)
            self.inbox_changed.emit(len(self.state.inbox))
            self.inbox_entry_removed.emit(tab_id)
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()
        elif not is_running and tab_id in self.state.inbox:
            self.state.remove_from_inbox(tab_id)
            self.inbox_changed.emit(len(self.state.inbox))
            self.inbox_entry_removed.emit(tab_id)
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()

        # Liga/desliga spinner
        if self.state.any_working() and not self._spinner_timer.isActive():
            self._spinner_timer.start()
        elif not self.state.any_working() and self._spinner_timer.isActive():
            self._spinner_timer.stop()

        self.tab_activity_changed.emit(
            tab_id, title, status, is_working, is_running, workspace_id, needs_decision
        )

    def _on_tab_removed(self, tab_id: int) -> None:
        self._prev_needs_decision.pop(tab_id, None)
        self._working_started_at.pop(tab_id, None)
        was_in_inbox = tab_id in self.state.inbox
        # Emite tab_removed ANTES de liberar o state — _handle_tab_removed
        # em main_window precisa ler state.tree_items[tab_id] pra achar o
        # QTreeWidgetItem e remover do tree + atualizar badge do bucket
        # Sessões Claude. Se liberar antes, o lookup volta None e a UI
        # fica dessincronizada (badge não decrementa).
        self.tab_removed.emit(tab_id)
        inbox_changed = self.state.release_tab(tab_id)
        if inbox_changed:
            self.inbox_changed.emit(len(self.state.inbox))
        if was_in_inbox:
            self.inbox_entry_removed.emit(tab_id)
        if not self.state.any_working():
            self._spinner_timer.stop()
        if not self.state.inbox and self._reminder_timer.isActive():
            self._reminder_timer.stop()

    def _on_tab_focused(self, area: TerminalArea, idx: int) -> None:
        if idx < 0:
            return
        widget = area.tabs.widget(idx)
        if widget is None:
            return
        tab_id = tab_uid_of(widget)
        if self.state.remove_from_inbox(tab_id):
            self.inbox_changed.emit(len(self.state.inbox))
            self.inbox_entry_removed.emit(tab_id)
            if not self.state.inbox and self._reminder_timer.isActive():
                self._reminder_timer.stop()

    # ---------- Inbox helpers ----------

    def inbox_count(self) -> int:
        return len(self.state.inbox)

    def inbox_entries(self) -> dict[int, dict]:
        return dict(self.state.inbox)

    def clear_inbox(self) -> None:
        ids = list(self.state.inbox.keys())
        self.state.clear_inbox()
        self.inbox_changed.emit(0)
        for tid in ids:
            self.inbox_entry_removed.emit(tid)
        if self._reminder_timer.isActive():
            self._reminder_timer.stop()

    def remove_from_inbox(self, tab_id: int) -> None:
        if self.state.remove_from_inbox(tab_id):
            self.inbox_changed.emit(len(self.state.inbox))
            self.inbox_entry_removed.emit(tab_id)
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
