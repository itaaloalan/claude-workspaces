"""TrayNotifier — sincroniza QSystemTrayIcon com NotificationService.

Pega um `QSystemTrayIcon` já criado e mantém tooltip + menu de contexto
reflectindo o estado do service. Não cria o tray (responsabilidade do
MainWindow), pra não duplicar lógica de inicialização nem assumir
disponibilidade de bandeja em testes.

Comportamento:

- Tooltip resume: "Claude Workspaces · 3 pendências (1 crítica)" ou
  "Claude Workspaces" (sem badge).
- Menu de contexto: até N pendências (default 5) com "Abrir", separador,
  "Mostrar janela", "Limpar histórico", "Sair".
- Clique em entrada do menu emite `open_target_requested(notification)`,
  consumido pelo MainWindow pra focar console.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .service import NotificationService
from .types import Notification, NotificationPriority

log = logging.getLogger(__name__)


class TrayNotifier(QObject):
    open_target_requested = Signal(object)  # Notification
    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        service: NotificationService,
        tray: QSystemTrayIcon,
        *,
        app_name: str = "Claude Workspaces",
        max_menu_items: int = 5,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._tray = tray
        self._app_name = app_name
        self._max_items = max(1, int(max_menu_items))
        self._menu = QMenu()
        self._tray.setContextMenu(self._menu)

        service.notification_added.connect(self._refresh)
        service.notification_changed.connect(self._refresh)
        service.notification_removed.connect(self._refresh)
        service.unread_count_changed.connect(self._refresh)

        self._refresh()

    def set_app_name(self, name: str) -> None:
        self._app_name = name
        self._refresh()

    # ---------------------------------------------------------------- update

    def _refresh(self, *_args) -> None:
        unread = self._service.list(only_unseen=True)
        critical = sum(
            1 for n in unread if n.priority == NotificationPriority.CRITICAL
        )
        if not unread:
            tooltip = self._app_name
        else:
            tail = f" ({critical} crítica{'s' if critical != 1 else ''})" if critical else ""
            tooltip = f"{self._app_name} · {len(unread)} pendência{'s' if len(unread) != 1 else ''}{tail}"
        try:
            self._tray.setToolTip(tooltip)
        except Exception:
            log.debug("setToolTip falhou", exc_info=True)
        self._rebuild_menu(unread)

    def _rebuild_menu(self, unread: list[Notification]) -> None:
        self._menu.clear()
        if unread:
            header = QAction(
                f"— {len(unread)} pendente{'s' if len(unread) != 1 else ''} —",
                self._menu,
            )
            header.setEnabled(False)
            self._menu.addAction(header)
            for n in unread[: self._max_items]:
                label = n.title
                if len(label) > 50:
                    label = label[:49] + "…"
                if n.priority == NotificationPriority.CRITICAL:
                    label = "⚠  " + label
                act = QAction(label, self._menu)
                act.triggered.connect(
                    lambda _c=False, _n=n: self.open_target_requested.emit(_n)
                )
                self._menu.addAction(act)
            if len(unread) > self._max_items:
                more = QAction(
                    f"… +{len(unread) - self._max_items} mais", self._menu
                )
                more.setEnabled(False)
                self._menu.addAction(more)
            self._menu.addSeparator()

        show = QAction("Mostrar janela", self._menu)
        show.triggered.connect(self.show_window_requested.emit)
        self._menu.addAction(show)

        if unread:
            clear = QAction("Marcar todas como vistas", self._menu)
            clear.triggered.connect(self._service.mark_all_seen)
            self._menu.addAction(clear)

        self._menu.addSeparator()
        quit_act = QAction("Sair", self._menu)
        quit_act.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(quit_act)


__all__ = ["TrayNotifier"]
