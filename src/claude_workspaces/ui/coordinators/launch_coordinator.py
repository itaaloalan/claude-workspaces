"""Coordena o fluxo 'Abrir Claude' / 'Abrir Terminal'.

Pega o workspace + parâmetros opcionais (resume, cwd override), pede
dialog quando aplicável, planeja via launch_planner, cria o terminal
via TerminalCoordinator, e inicia o pty.

Não toca QTreeWidget nem dock — só TerminalCoordinator + dialogs.
"""

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from ...briefing_builder import build_briefing
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
        initial_prompt = ""
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
            initial_prompt = dialog.result_initial_prompt()

        argv = build_claude_argv(
            self.settings.claude_command,
            self.settings.claude_launch_args(),
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
        if initial_prompt:
            # Why: Claude CLI 2.1.x trava (tela preta) com prompt
            # posicional >~500 chars junto de --add-dir (ver 0.27.1).
            # Mais robusto: deixar a TUI subir e digitar o prompt via
            # PTY, como se o usuário tivesse digitado.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                1500, lambda t=terminal, p=initial_prompt: t.send_text(p)
            )
        self.sessions_refresh_requested.emit()
        return terminal

    def launch_shell(
        self, workspace: Workspace, cwd_override: str | None = None
    ) -> TerminalWidget | None:
        if not workspace.folders:
            return None
        cwd = cwd_override or workspace.launch_paths()[0]
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

        primary = workspace.primary_folder() or ""
        briefing_text = build_briefing(session, primary)

        dialog = HandoffDialog(session, briefing_text, parent=self._parent_window)
        if not dialog.exec():
            return
        briefing = dialog.briefing()
        if not briefing:
            return
        # Clipboard sempre — fallback se autodetect falhar
        QGuiApplication.clipboard().setText(briefing)
        terminal = self.launch_claude(workspace, "", "")
        if terminal is None:
            return

        def _on_ready(success: bool) -> None:
            if success:
                self._send_briefing(terminal, briefing)
            else:
                log.warning(
                    "Claude não ficou pronto a tempo — briefing fica no clipboard"
                )
                QMessageBox.information(
                    self._parent_window,
                    "Briefing no clipboard",
                    "Não consegui detectar o Claude pronto pra receber input. "
                    "O briefing está no clipboard — cole quando ele subir.",
                )

        terminal.when_claude_ready(_on_ready, timeout_ms=30000)

    @staticmethod
    def _send_briefing(terminal: TerminalWidget, text: str) -> None:
        if not terminal.session.is_running():
            log.warning("Terminal não está rodando, abortando envio de briefing")
            return
        try:
            terminal.session.write((text + "\n").encode("utf-8"))
        except Exception:
            log.exception("Falha ao enviar briefing pro terminal")
