"""Coordena CRUD de workspaces + cache de texto de sessões pro filtro.

Owner de:
- list[Workspace] persistido em ~/.config/claude-workspaces/workspaces.json
- _session_text_cache (lazy, invalidado em edit/delete)

Não toca em widgets — emite signals pra MainWindow rebuilds.
"""

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from ...models import Workspace
from ...storage import load_workspaces, save_workspaces

log = logging.getLogger(__name__)


class WorkspaceCoordinator(QObject):
    workspaces_changed = Signal()       # lista mudou (add/edit/delete)
    workspace_deleted = Signal(str)     # workspace_id deletado

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.workspaces: list[Workspace] = load_workspaces()
        self._session_text_cache: dict[str, str] = {}
        self._migrate_ids_if_needed()

    def _migrate_ids_if_needed(self) -> None:
        # from_dict já preenche id ausente; força um save pra persistir
        # caso o arquivo antigo não tivesse ids.
        if self.workspaces:
            save_workspaces(self.workspaces)

    # ---------- CRUD ----------

    def add(self, workspace: Workspace) -> None:
        self.workspaces.append(workspace)
        save_workspaces(self.workspaces)
        self.workspaces_changed.emit()

    def replace(self, workspace: Workspace, emit: bool = True) -> bool:
        """Substitui um workspace pelo id. Retorna True se encontrou.

        `emit=False` salva sem emitir `workspaces_changed` — pra mudanças
        que já atualizaram a UI na mão (ex.: cwd de runner) e não precisam
        do rebuild completo da sidebar que o signal dispara."""
        idx = next(
            (i for i, w in enumerate(self.workspaces) if w.id == workspace.id),
            None,
        )
        if idx is None:
            return False
        self.workspaces[idx] = workspace
        save_workspaces(self.workspaces)
        self._session_text_cache.pop(workspace.id, None)
        if emit:
            self.workspaces_changed.emit()
        return True

    def delete(self, workspace_id: str) -> bool:
        before = len(self.workspaces)
        self.workspaces = [w for w in self.workspaces if w.id != workspace_id]
        if len(self.workspaces) == before:
            return False
        save_workspaces(self.workspaces)
        self._session_text_cache.pop(workspace_id, None)
        self.workspace_deleted.emit(workspace_id)
        self.workspaces_changed.emit()
        return True

    def set_pinned(self, workspace_id: str, pinned: bool) -> bool:
        ws = self.find_by_id(workspace_id)
        if ws is None or ws.pinned == pinned:
            return False
        ws.pinned = pinned
        save_workspaces(self.workspaces)
        self.workspaces_changed.emit()
        return True

    def set_minimized(self, workspace_id: str, minimized: bool) -> bool:
        ws = self.find_by_id(workspace_id)
        if ws is None or ws.minimized == minimized:
            return False
        ws.minimized = minimized
        save_workspaces(self.workspaces)
        self.workspaces_changed.emit()
        return True

    def find_by_id(self, workspace_id: str) -> Workspace | None:
        return next(
            (w for w in self.workspaces if w.id == workspace_id), None
        )

    def find_for_cwd(self, cwd: str) -> Workspace | None:
        """Acha o workspace cuja primeira pasta == cwd, ou que contenha cwd."""
        for ws in self.workspaces:
            for folder in ws.folders:
                if folder == cwd or cwd.startswith(folder + "/"):
                    return ws
        return None

    # ---------- Confirm delete ----------

    def confirm_delete(
        self, workspace: Workspace, parent: QWidget | None = None
    ) -> bool:
        reply = QMessageBox.question(
            parent,
            "Remover workspace",
            f"Remover o workspace '{workspace.name}'?",
        )
        return reply == QMessageBox.StandardButton.Yes

    # ---------- Filter cache ----------

    def session_text_for(self, workspace: Workspace) -> str:
        """Lazy cache do preview das últimas sessões — usado pelo filtro
        do topbar. Não bloqueia se a leitura falhar."""
        if workspace.id in self._session_text_cache:
            return self._session_text_cache[workspace.id]
        text = ""
        if workspace.folders:
            try:
                from ...claude_sessions import list_sessions_for_paths
                cwd, _ = workspace.launch_paths()
                paths = list({cwd, *workspace.folders})
                sessions = list_sessions_for_paths(paths, limit=15)
                text = " ".join(s.preview for s in sessions if s.preview)
            except Exception:
                log.debug("session_text_for falhou em %s", workspace.id)
        self._session_text_cache[workspace.id] = text
        return text

    def invalidate_cache(self, workspace_id: str | None = None) -> None:
        if workspace_id is None:
            self._session_text_cache.clear()
        else:
            self._session_text_cache.pop(workspace_id, None)
