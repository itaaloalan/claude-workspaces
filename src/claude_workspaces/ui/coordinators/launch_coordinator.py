"""Coordena o fluxo 'Abrir Claude' / 'Abrir Terminal'.

Pega o workspace + parâmetros opcionais (resume, cwd override), pede
dialog quando aplicável, planeja via launch_planner, cria o terminal
via TerminalCoordinator, e inicia o pty.

Não toca QTreeWidget nem dock — só TerminalCoordinator + dialogs.
"""

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from ...claude_sessions import ClaudeSession
from ...models import Workspace
from ...services.launch_planner import build_claude_argv, plan_from_dialog
from ...settings import Settings
from ..terminal_widget import TerminalWidget
from .terminal_coordinator import TerminalCoordinator

log = logging.getLogger(__name__)


class LaunchCoordinator(QObject):
    sessions_refresh_requested = Signal()  # WorkspaceDetailsPanel reage
    workspace_focus_requested = Signal(str)  # MainWindow seleciona ws

    def __init__(
        self,
        settings: Settings,
        terminals: TerminalCoordinator,
        parent_window: QWidget,
    ) -> None:
        super().__init__(parent_window)
        self.settings = settings
        self.terminals = terminals
        self._parent_window = parent_window

    # ---------- Claude ----------

    def launch_claude(
        self,
        workspace: Workspace,
        resume_session_id: str = "",
        cwd_override: str = "",
    ) -> TerminalWidget | None:
        """Fluxo principal. Devolve o TerminalWidget criado ou None se
        usuário cancelou / falhou."""
        if not workspace.folders:
            QMessageBox.warning(
                self._parent_window,
                "Workspace sem pastas",
                "Adicione pelo menos uma pasta.",
            )
            return None

        cwd, extras = workspace.launch_paths()
        worktree_label = ""
        if cwd_override:
            cwd = cwd_override
            extras = []
        elif not resume_session_id:
            # Importa local pra evitar circular import e custo de
            # importar Qt widgets pesados em testes
            from ..launch_claude_dialog import LaunchClaudeDialog
            dialog = LaunchClaudeDialog(workspace, self.settings, parent=self._parent_window)
            if not dialog.exec():
                return None
            plan = plan_from_dialog(
                dialog.result_folders(),
                dialog.result_isolate(),
                dialog.result_create_branch(),
                dialog.result_branch(),
                dialog.result_base_branch(),
            )
            if not plan.ok:
                if plan.error:
                    QMessageBox.warning(
                        self._parent_window,
                        "Falha ao preparar launch",
                        plan.error,
                    )
                return None
            cwd, extras = plan.cwd, plan.extras
            worktree_label = plan.worktree_label

        argv = build_claude_argv(
            self.settings.claude_command,
            self.settings.claude_extra_args,
            extras,
            resume_session_id,
        )

        area = self.terminals.get_or_create_area(workspace)
        title = "claude (resume)" if resume_session_id else "claude"
        title = f"{title} #{area.count() + 1}{worktree_label}"
        terminal = area.add_terminal(title)
        terminal.configure_claude(cwd, resume_session_id or None)
        label = f"claude — {workspace.name}{worktree_label}"
        try:
            terminal.start_shell_command(
                argv,
                cwd,
                label=label,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir Claude embutido")
            QMessageBox.warning(self._parent_window, "Falha", str(e))
            return None
        self.sessions_refresh_requested.emit()
        return terminal

    def launch_shell(self, workspace: Workspace) -> TerminalWidget | None:
        if not workspace.folders:
            return None
        cwd, _ = workspace.launch_paths()
        area = self.terminals.get_or_create_area(workspace)
        terminal = area.add_terminal(f"shell #{area.count() + 1}")
        try:
            terminal.start_interactive_shell(
                cwd,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao abrir shell embutido")
            QMessageBox.warning(self._parent_window, "Falha", str(e))
            return None
        return terminal

    # ---------- Handoff ----------

    def handoff_session(
        self, workspace: Workspace, session: ClaudeSession
    ) -> None:
        from ..handoff_dialog import HandoffDialog
        dialog = HandoffDialog(session, parent=self._parent_window)
        if not dialog.exec():
            return
        briefing = dialog.briefing()
        if not briefing:
            return
        QGuiApplication.clipboard().setText(briefing)
        terminal = self.launch_claude(workspace, "", "")
        if terminal is None:
            return
        QTimer.singleShot(
            4000, lambda: self._send_briefing(terminal, briefing)
        )

    @staticmethod
    def _send_briefing(terminal: TerminalWidget, text: str) -> None:
        if not terminal.session.is_running():
            log.warning("Terminal não está rodando, abortando envio de briefing")
            return
        try:
            terminal.session.write((text + "\n").encode("utf-8"))
        except Exception:
            log.exception("Falha ao enviar briefing pro terminal")
