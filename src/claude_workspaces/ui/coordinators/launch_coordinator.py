"""Coordena o fluxo 'Abrir Claude' / 'Abrir Terminal'.

Pega o workspace + parâmetros opcionais (resume, cwd override), pede
dialog quando aplicável, planeja via launch_planner, cria o terminal
via TerminalCoordinator, e inicia o pty.

Não toca QTreeWidget nem dock — só TerminalCoordinator + dialogs.
"""

import logging
import os
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from ...briefing_builder import build_briefing
from ...claude_sessions import ClaudeSession
from ...models import Workspace
from ...services.launch_planner import build_ai_argv, plan_from_dialog
from ...settings import Settings
from ..terminal_widget import TerminalWidget
from .terminal_coordinator import TerminalCoordinator

log = logging.getLogger(__name__)


@dataclass
class ReloadResult:
    """Resultado de `reload_session` — feedback honesto pro caller decidir
    o toast/aviso. `reason` resume o que de fato aconteceu:
    - "worktree": o processo migrou pra uma worktree adotada (cwd mudou).
    - "same_dir": recarregou no mesmo cwd (ex.: /trocar-banco regenerou MCP).
    - "no_session": session_id ainda não resolvido — nada feito.
    - "error": exceção ao subir o processo.
    """
    ok: bool
    reason: str
    cwd_changed: bool = False
    is_worktree: bool = False
    cwd: str = ""
    worktree_label: str = ""


def _opencode_extra_dirs_prompt(extras: list[str]) -> str:
    dirs = "\n".join(f"- {p}" for p in extras)
    return (
        "Contexto adicional deste workspace:\n"
        f"{dirs}\n\n"
        "Quando precisar consultar arquivos fora do diretório principal, use esses "
        "caminhos absolutos como parte do contexto da tarefa."
    )


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
        backend_override: str = "",
        skip_dialog: bool = False,
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
        is_worktree = False
        initial_prompt = ""
        submit_initial_prompt = False
        if cwd_override:
            cwd, extras, worktree_label, is_worktree = self._cwd_context_from_override(
                workspace, cwd_override
            )
        elif not resume_session_id and not skip_dialog:
            # Importa local pra evitar circular import e custo de
            # importar Qt widgets pesados em testes
            from ..launch_claude_dialog import LaunchClaudeDialog
            dialog = LaunchClaudeDialog(workspace, self.settings, parent=self._parent_window)
            if not dialog.exec():
                return None
            existing_wt = dialog.result_existing_worktree()
            if existing_wt is not None:
                repo_folder, wt_path, wt_branch = existing_wt
                cwd = wt_path
                from ...git_worktree import translate_dir_for_repo
                # Irmãos traduzidos pro worktree na mesma branch (quando
                # existir); senão caem no principal. repo_folder já é excluído.
                extras = [
                    translate_dir_for_repo(wt_path, f) or f
                    for f in dialog.result_folders() if f != repo_folder
                ]
                worktree_label = f" · {wt_branch}" if wt_branch else " · isolado"
                is_worktree = True
            else:
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
                is_worktree = plan.is_worktree
            initial_prompt = dialog.result_initial_prompt()
            submit_initial_prompt = bool(initial_prompt.strip())

        argv, backend = self._build_ai_args(
            workspace, extras, resume_session_id, backend_override
        )
        if backend == "opencode" and extras:
            extra_context = _opencode_extra_dirs_prompt(extras)
            initial_prompt = (
                f"{extra_context}\n\n{initial_prompt}"
                if initial_prompt.strip()
                else extra_context
            )

        area = self.terminals.get_or_create_area(workspace)
        backend_short = "opencode" if backend == "opencode" else "claude"
        title = f"{backend_short} (resume)" if resume_session_id else backend_short
        title = f"{title}{worktree_label}"
        terminal = area.add_terminal(title)
        terminal.configure_claude(cwd, resume_session_id or None, backend=backend)
        terminal.set_context_info(
            cwd, extras,
            worktree_label=worktree_label,
            is_worktree=is_worktree,
            workspace_folders=list(workspace.folders),
        )
        label = f"{backend_short} — {workspace.name}{worktree_label}"
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
                1500,
                lambda t=terminal, p=initial_prompt, s=submit_initial_prompt: t.send_text(
                    p, submit=s
                ),
            )
        self.sessions_refresh_requested.emit()
        return terminal

    def _cwd_context_from_override(
        self, workspace: Workspace, cwd_override: str
    ) -> tuple[str, list[str], str, bool]:
        """Resolve (cwd, extras, worktree_label, is_worktree) a partir de um
        cwd explícito — worktree de um repo, pasta-pai de grupo, ou pasta
        comum. Usado pelo launch com cwd_override e pelo reload da sessão."""
        cwd = cwd_override
        from ...git_worktree import (
            current_branch,
            is_worktree_group,
            is_worktree_path,
            translate_dir_for_repo,
            worktree_group_members,
        )
        if is_worktree_path(cwd):
            # cwd é o worktree de UM repo. As pastas do workspace são os
            # repos PRINCIPAIS; cada uma vira seu worktree-irmão na mesma
            # branch (quando existir) e o repo do próprio cwd é excluído
            # pra não duplicar. Sem isso o filtro `f != cwd_override` era
            # no-op (worktree != path do principal) → todos os principais
            # entravam, duplicando o repo do cwd e abrindo os irmãos no
            # checkout principal em vez do worktree-irmão.
            extras = []
            for f in workspace.folders:
                tr = translate_dir_for_repo(cwd, f)
                if tr == cwd:            # mesmo repo do cwd → não duplica
                    continue
                extras.append(tr or f)   # irmão-worktree, ou principal
            br = current_branch(cwd)
            worktree_label = f" · {br}" if br else " · isolado"
            return cwd, extras, worktree_label, True
        if is_worktree_group(cwd):
            # Pasta-pai do grupo: cada membro é o worktree de UM repo.
            # Sem popular extras, o console não recebia as pastas-irmãs
            # (--add-dir do Claude, painel Git, abrir no editor) e tudo a
            # jusante enxergava só uma pasta.
            members = worktree_group_members(cwd)
            extras = [m["path"] for m in members]
            br = members[0]["branch"] if members else ""
            worktree_label = f" · {br}" if br else " · grupo"
            return cwd, extras, worktree_label, True
        extras = [f for f in workspace.folders if f != cwd_override]
        return cwd, extras, "", False

    def _build_ai_args(
        self,
        workspace: Workspace,
        extras: list[str],
        resume_session_id: str,
        backend_override: str,
    ) -> tuple[list[str], str]:
        """Monta o argv do backend (claude/opencode) + regenera a config MCP
        do workspace. Devolve (argv, backend). Fonte única usada pelo launch
        e pelo reload."""
        backend = backend_override or self.settings.ai_backend
        if backend == "opencode":
            command = self.settings.opencode_command or "opencode"
            launch_args = [
                *self.settings.opencode_extra_args,
                *self.settings.opencode_session_flags(),
            ]
        else:
            command = self.settings.claude_command or "claude"
            launch_args = self.settings.claude_launch_args()
        # Escopo de MCP por workspace: gera um arquivo de config só com os MCP
        # que este workspace precisa e passa --mcp-config --strict-mcp-config.
        # Regerar aqui faz o reload pegar mudanças de MCP/banco feitas após o
        # launch (ex.: /trocar-banco que reescreveu o MCP no ~/.claude.json).
        mcp_config_path = ""
        if backend != "opencode" and self.settings.mcp_scope_per_workspace:
            try:
                from ...services.mcp_scope import write_workspace_mcp_config
                mcp_config_path = write_workspace_mcp_config(workspace) or ""
            except Exception:
                log.debug("Falha gerando config MCP do workspace", exc_info=True)
        argv = build_ai_argv(
            backend,
            command,
            launch_args,
            extras,
            resume_session_id,
            mcp_config_path,
        )
        return argv, backend

    def reload_session(
        self, terminal: TerminalWidget, workspace: Workspace, *, silent: bool = False
    ) -> ReloadResult:
        """Reinicia o processo do console mantendo o contexto: mata o backend
        atual e relança com `--resume <session_id>`, no cwd vigente (worktree
        adotado em runtime, se houver) e regerando a config MCP. Resolve os
        dois casos onde hoje é preciso reabrir a sessão na mão: criar uma
        worktree (o processo continuava no cwd antigo) e trocar o banco (MCP
        com a conexão velha).

        Com `silent=True` (auto-reload por adoção de worktree) NUNCA mostra
        QMessageBox — devolve o motivo no ReloadResult pro caller decidir.
        """
        old_cwd = terminal.claude_cwd() or ""
        sid = terminal.claimed_session_id()
        if not sid:
            if not silent:
                QMessageBox.information(
                    self._parent_window,
                    "Recarregar sessão",
                    "A sessão ainda não foi identificada — aguarde alguns "
                    "segundos após o Claude subir e tente de novo.",
                )
            return ReloadResult(ok=False, reason="no_session")
        # Worktree adotado em runtime vira o novo cwd; senão mantém o cwd atual.
        new_cwd = terminal.worktree_dir() or terminal.claude_cwd() or ""
        if not new_cwd:
            return ReloadResult(ok=False, reason="noop")
        cwd, extras, worktree_label, is_worktree = self._cwd_context_from_override(
            workspace, new_cwd
        )
        cwd_changed = os.path.realpath(cwd) != os.path.realpath(old_cwd)
        backend = terminal.backend() or self.settings.ai_backend
        argv, backend = self._build_ai_args(workspace, extras, sid, backend)
        backend_short = "opencode" if backend == "opencode" else "claude"
        # O Claude indexa sessões por cwd: `--resume <sid>` só acha o JSONL no
        # projeto do cwd atual. Se o reload muda o cwd (worktree adotado em
        # runtime), o arquivo da sessão fica no projeto do cwd antigo e o
        # resume falha com "No conversation found with session ID". Copiamos o
        # JSONL pro projeto do novo cwd antes de subir, preservando o contexto.
        if backend != "opencode":
            self._ensure_session_in_cwd(terminal, sid, cwd)
        # Solta o claim antigo: o _try_resolve_session re-vincula o id (agora
        # presente no novo cwd) migrando o custom_name. Sem soltar, o widget
        # ficaria preso no claim anterior.
        terminal.release_session_claim()
        terminal.configure_claude(cwd, sid, backend=backend)
        terminal.set_context_info(
            cwd, extras,
            worktree_label=worktree_label,
            is_worktree=is_worktree,
            workspace_folders=list(workspace.folders),
        )
        label = f"{backend_short} — {workspace.name}{worktree_label}"
        try:
            # start_shell_command → _start_now mata o PTY atual antes de subir.
            terminal.start_shell_command(
                argv,
                cwd,
                label=label,
                shell=self.settings.shell_command or None,
            )
        except Exception as e:
            log.exception("Falha ao recarregar sessão")
            if not silent:
                QMessageBox.warning(self._parent_window, "Falha", str(e))
            return ReloadResult(ok=False, reason="error", cwd=cwd)
        # Quando o Claude voltar a ficar pronto (idle), injeta uma mensagem
        # confirmando o reload + o contexto vigente (worktree + MCPs), pra ele
        # saber em que diretório/ferramentas está operando agora.
        msg = self._reload_confirmation_message(
            cwd, worktree_label, is_worktree, workspace
        )
        terminal.when_claude_ready(
            lambda ok, t=terminal, m=msg: t.send_text(m, submit=True) if ok else None,
            timeout_ms=30000,
        )
        self.sessions_refresh_requested.emit()
        return ReloadResult(
            ok=True,
            reason="worktree" if (is_worktree and cwd_changed) else "same_dir",
            cwd_changed=cwd_changed,
            is_worktree=is_worktree,
            cwd=cwd,
            worktree_label=worktree_label,
        )

    @staticmethod
    def _ensure_session_in_cwd(
        terminal: TerminalWidget, session_id: str, new_cwd: str
    ) -> None:
        """Garante que o JSONL da sessão exista no projeto do `new_cwd`, pra que
        `claude --resume <session_id>` o encontre. Procura o arquivo onde ele
        está hoje (cwd antigo do terminal, ou varrendo ~/.claude/projects) e o
        copia pro diretório do novo cwd. No-op se o arquivo já estiver lá ou se
        a origem não for localizável."""
        import shutil

        from ...claude_sessions import find_session_file, project_sessions_dir

        dest_dir = project_sessions_dir(new_cwd)
        dest = dest_dir / f"{session_id}.jsonl"
        if dest.is_file():
            return
        src = terminal.claimed_session_path()
        if src is None or not src.is_file() or src.suffix != ".jsonl":
            src = find_session_file(session_id)
        if src is None or src == dest:
            return
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            log.info("sessão %s copiada de %s para %s", session_id, src, dest)
        except OSError:
            log.warning(
                "não consegui copiar a sessão %s para %s — resume pode falhar",
                session_id, dest, exc_info=True,
            )

    @staticmethod
    def _reload_confirmation_message(
        cwd: str, worktree_label: str, is_worktree: bool, workspace: Workspace
    ) -> str:
        """Mensagem injetada no console após o reload, confirmando o estado
        do contexto pro Claude (worktree atual + MCPs disponíveis)."""
        branch = worktree_label.strip().lstrip("·").strip()
        if is_worktree:
            wt_line = f"🌿 Worktree: {branch or '(isolado)'} — `{cwd}`"
        else:
            wt_line = f"📁 Diretório: `{cwd}` (sem worktree isolado)"
        try:
            # Mesma resolução que o launcher usa pra --mcp-config
            # --strict-mcp-config: os MCP de fato ativos na sessão (override
            # explícito ou auto-inferido pelo nome/pastas do workspace),
            # não os globais crus do ~/.claude.json.
            from ...services.mcp_scope import resolve_mcp_servers
            mcps = sorted(resolve_mcp_servers(workspace))
        except Exception:
            mcps = []
        mcp_line = (
            "🔌 MCPs neste contexto: " + ", ".join(mcps)
            if mcps else "🔌 MCPs neste contexto: nenhum"
        )
        return (
            "[reload automático] A sessão foi recarregada — o processo "
            "reiniciou e o contexto foi preservado via --resume. "
            "Contexto atual:\n"
            f"- {wt_line}\n"
            f"- {mcp_line}\n"
            "Pode continuar de onde paramos."
        )

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

        ai_name = self.settings.ai_command()
        def _on_ready(success: bool) -> None:
            if success:
                self._send_briefing(terminal, briefing)
            else:
                log.warning(
                    "%s não ficou pronto a tempo — briefing fica no clipboard", ai_name
                )
                QMessageBox.information(
                    self._parent_window,
                    "Briefing no clipboard",
                    f"Não consegui detectar o {ai_name} pronto pra receber input. "
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
