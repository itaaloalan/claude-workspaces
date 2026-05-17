"""PluginCoordinator — encapsula a integração entre MainWindow e o
subsistema de plugins.

Antes vivia inflando main_window.py com ~200 linhas de wiring: init do
PluginHost, providers, cache de sessões, dispatch de session.* events,
hot-reload de plugins.

Aqui mora isolado. MainWindow só precisa instanciar e chamar:
- `init(plugins_view, git_panel)` para acoplar dependencies que existem
  só depois do _build_ui
- `dispatch_session_event(...)` quando uma aba muda de estado
- `dispatch_tab_removed(tab_id)` quando uma aba fecha
- `dispatch_workspace_opened(ws_id)` e `dispatch_workspace_closed(ws_id)`
- `shutdown()` no closeEvent
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ...models import Workspace

log = logging.getLogger(__name__)


class PluginCoordinator(QObject):
    """Wrapper Qt-aware do PluginHost.

    Vive desde o construtor da MainWindow mas o host real só sobe em
    `init()` (depende de coordinators já prontos).
    """

    notification_received = Signal(str, str, dict)  # plugin_id, kind, payload

    def __init__(
        self,
        workspace_lookup: Callable[[str], Workspace | None],
        current_workspace_fn: Callable[[], Workspace | None],
        all_workspaces_fn: Callable[[], list[Workspace]],
        focus_tab_fn: Callable[[str, int], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace_lookup = workspace_lookup
        self._current_workspace_fn = current_workspace_fn
        self._all_workspaces_fn = all_workspaces_fn
        self._focus_tab_fn = focus_tab_fn
        self._host = None
        self._session_cache: dict[int, dict] = {}
        self._plugins_view = None

    @property
    def host(self):
        return self._host

    @property
    def session_cache(self) -> dict[int, dict]:
        return self._session_cache

    def init(self, plugins_view, git_panel) -> None:
        """Sobe o subsistema de plugins. Falha aqui não derruba o app — o
        host vira `None` e o resto roda normal."""
        self._plugins_view = plugins_view
        try:
            from ...plugin_api import Session as PluginSession
            from ...plugin_api import Workspace as PluginWorkspace
            from ...services.plugin_host import PluginHost

            def ws_to_plugin(ws: Workspace) -> PluginWorkspace:
                return PluginWorkspace(
                    id=ws.id, name=ws.name, folders=tuple(ws.folders)
                )

            def list_ws() -> list[PluginWorkspace]:
                return [ws_to_plugin(w) for w in self._all_workspaces_fn()]

            def current_ws() -> PluginWorkspace | None:
                ws = self._current_workspace_fn()
                return ws_to_plugin(ws) if ws else None

            def list_sessions(status_filter: str | None) -> list[PluginSession]:
                out: list[PluginSession] = []
                for tab_id, meta in self._session_cache.items():
                    if status_filter and meta["status"] != status_filter:
                        continue
                    out.append(
                        PluginSession(
                            id=str(tab_id),
                            workspace_id=meta["workspace_id"],
                            workspace_name=meta["workspace_name"],
                            status=meta["status"],
                            last_message=meta.get("title"),
                        )
                    )
                return out

            def focus_session(session_id: str) -> None:
                try:
                    tab_id = int(session_id)
                except ValueError:
                    return
                meta = self._session_cache.get(tab_id)
                if meta is None:
                    return
                self._focus_tab_fn(meta["workspace_id"], tab_id)

            self._host = PluginHost(
                ws_list_provider=list_ws,
                ws_current_provider=current_ws,
                sessions_list_provider=list_sessions,
                session_focus_fn=focus_session,
            )
            self._host.notifications.connect(self._on_plugin_notification)
            # PluginsView dispara load/unload do runtime quando o usuário
            # instala, desinstala, habilita ou desabilita pela UI.
            plugins_view.set_runtime_reloader(self._reload_plugin_runtime)
            plugins_view.set_test_runner(self._run_test)
            try:
                git_panel.commit_created.connect(self._on_commit_created)
            except Exception:
                log.exception("Falha conectando commit_created ao plugin host")
            log.info(
                "Plugin host iniciado (%d plugin(s) carregado(s))",
                len(self._host.runtime._modules),
            )
        except Exception:
            log.exception("Falha iniciando plugin host — plugins ficam desligados")

    def shutdown(self) -> None:
        try:
            if self._host is not None:
                self._host.shutdown()
        except Exception:
            log.exception("Falha desligando plugin host")

    def open_palette(self, parent_widget) -> None:
        if self._host is None:
            return
        from ..plugin_palette_dialog import PluginPaletteDialog

        dlg = PluginPaletteDialog(self._host, parent=parent_widget)
        dlg.exec()

    def dispatch_workspace_opened(self, workspace_id: str) -> None:
        if self._host is not None:
            self._host.publish("workspace.opened", {"workspaceId": workspace_id})

    def dispatch_workspace_closed(self, workspace_id: str) -> None:
        if self._host is not None:
            self._host.publish("workspace.closed", {"workspaceId": workspace_id})

    def dispatch_session_event(
        self,
        tab_id: int,
        workspace_id: str,
        title: str,
        is_working: bool,
        is_running: bool,
    ) -> None:
        """Mantém o cache de sessões e despacha session.* pro plugin bus.

        Tradução: 1ª vez vendo tab_id → session.created. Mudança de status
        no cache → session.status-changed. is_running=False → session.completed."""
        if self._host is None:
            return
        ws = self._workspace_lookup(workspace_id)
        ws_name = ws.name if ws else workspace_id
        new_status = _plugin_session_status_for(is_working, is_running)
        cached = self._session_cache.get(tab_id)
        now = time.monotonic()
        if cached is None:
            self._session_cache[tab_id] = {
                "workspace_id": workspace_id,
                "workspace_name": ws_name,
                "status": new_status,
                "title": title,
                "created_at_mono": now,
                "last_change_mono": now,
            }
            self._publish_session_event(
                "session.created",
                tab_id,
                {
                    "workspaceId": workspace_id,
                    "createdAt": datetime.now().isoformat(timespec="seconds"),
                },
            )
            return

        cached["title"] = title
        cached["workspace_name"] = ws_name

        old_status = cached["status"]
        if new_status != old_status:
            duration_ms = max(0, int((now - cached["last_change_mono"]) * 1000))
            cached["status"] = new_status
            cached["last_change_mono"] = now
            self._publish_session_event(
                "session.status-changed",
                tab_id,
                {
                    "oldStatus": old_status,
                    "newStatus": new_status,
                    "durationMs": duration_ms,
                },
            )
            if new_status == "completed":
                total_ms = max(0, int((now - cached["created_at_mono"]) * 1000))
                self._publish_session_event(
                    "session.completed",
                    tab_id,
                    {"reason": "ended", "durationMs": total_ms},
                )

    def dispatch_tab_removed(self, tab_id: int) -> None:
        if self._host is None:
            return
        cached = self._session_cache.pop(tab_id, None)
        if cached and cached.get("status") != "completed":
            duration_ms = max(
                0, int((time.monotonic() - cached["created_at_mono"]) * 1000)
            )
            self._publish_session_event(
                "session.completed",
                tab_id,
                {"reason": "closed", "durationMs": duration_ms},
            )

    def _publish_session_event(
        self, event: str, tab_id: int, extra: dict | None = None
    ) -> None:
        if self._host is None:
            return
        payload = {"sessionId": str(tab_id)}
        if extra:
            payload.update(extra)
        self._host.publish(event, payload)

    def _on_plugin_notification(
        self, plugin_id: str, kind: str, payload: dict
    ) -> None:
        log.info("plugin %s %s: %s", plugin_id, kind, payload)
        self.notification_received.emit(plugin_id, kind, payload)

    def _on_commit_created(
        self, workspace_id: str, _folder: str, sha: str, message: str
    ) -> None:
        if self._host is None:
            return
        self._host.publish(
            "commit.created",
            {"workspaceId": workspace_id, "sha": sha, "message": message},
        )

    def _run_test(self, plugin_id: str, kind: str, identifier: str) -> dict:
        """Dispara manualmente algo do plugin (hook/command/panel) com payload
        sintético, pra que o usuário confirme visualmente que funciona.

        kind:
          - 'hook'    → publica o evento `identifier` com payload sintético
                        (usando workspace/sessão reais quando disponíveis).
                        Note que TODOS plugins inscritos no evento recebem.
          - 'command' → invoca direto `runtime.invoke_command(plugin_id, identifier)`.
          - 'panel'   → constrói o QWidget e retorna em result['widget'].

        Retorna `{'ok': bool, 'message': str, ...}` que a UI mostra ao usuário."""
        if self._host is None:
            return {"ok": False, "message": "plugin host não está disponível"}
        log.info(
            "[%s] test runner: kind=%s id=%s", plugin_id, kind, identifier
        )
        if kind == "command":
            try:
                self._host.runtime.invoke_command(plugin_id, identifier)
            except Exception as e:
                log.exception("[%s] teste de command %s falhou", plugin_id, identifier)
                return {"ok": False, "message": f"erro: {e}"}
            return {
                "ok": True,
                "message": (
                    f"command '{identifier}' invocado — veja o resultado na UI "
                    f"(notificação, log, etc.)"
                ),
            }
        if kind == "panel":
            try:
                widget = self._host.runtime.build_panel(plugin_id, identifier)
            except Exception as e:
                log.exception("[%s] teste de panel %s falhou", plugin_id, identifier)
                return {"ok": False, "message": f"erro construindo panel: {e}"}
            if widget is None:
                return {"ok": False, "message": "build_panel retornou None"}
            return {"ok": True, "message": "panel construído", "widget": widget}
        if kind == "hook":
            payload = self._synthetic_payload(identifier)
            n = self._host.publish(identifier, payload)
            msg = (
                f"evento '{identifier}' publicado com payload sintético "
                f"→ {n} subscriber(s) recebeu(am)"
            )
            if n == 0:
                msg += (
                    " — nenhum plugin escutava esse evento (esperado se o "
                    "plugin tá disabled)"
                )
            return {"ok": True, "message": msg, "payload": payload}
        return {"ok": False, "message": f"kind desconhecido: {kind!r}"}

    def _synthetic_payload(self, event: str) -> dict:
        """Monta payload sintético plausível pro evento, reusando IDs reais
        de workspace/sessão quando disponíveis pra que hooks que fazem
        `ctx.sessions.get(...)` consigam resolver."""
        now_iso = datetime.now().isoformat(timespec="seconds")
        # workspace real, se houver
        ws = self._current_workspace_fn()
        ws_id = ws.id if ws else "test-workspace"
        # sessão real (qualquer uma do cache)
        session_id = "test-session-001"
        for tab_id in self._session_cache:
            session_id = str(tab_id)
            break
        if event == "session.created":
            return {
                "sessionId": session_id,
                "workspaceId": ws_id,
                "createdAt": now_iso,
            }
        if event == "session.status-changed":
            # 30 min em awaiting-input — passa de qualquer threshold padrão
            return {
                "sessionId": session_id,
                "oldStatus": "running",
                "newStatus": "awaiting-input",
                "durationMs": 30 * 60 * 1000,
            }
        if event == "session.message-sent":
            return {
                "sessionId": session_id,
                "messageId": "test-msg-001",
                "length": 42,
            }
        if event == "session.completed":
            return {
                "sessionId": session_id,
                "reason": "ended",
                "durationMs": 5 * 60 * 1000,
            }
        if event == "workspace.opened":
            return {"workspaceId": ws_id}
        if event == "workspace.closed":
            return {"workspaceId": ws_id}
        if event == "commit.created":
            return {
                "workspaceId": ws_id,
                "sha": "test1234abc",
                "message": "(teste) commit sintético disparado da UI",
            }
        if event == "plugin.config-changed":
            return {
                "key": "exemplo",
                "oldValue": None,
                "newValue": "teste",
            }
        return {}

    def _reload_plugin_runtime(self, plugin_id: str, action: str) -> None:
        """Aciona o runtime quando a PluginsView muda o estado do plugin.

        action: 'load' (depois de install/enable) ou 'unload' (uninstall/disable)."""
        if self._host is None:
            return
        runtime = self._host.runtime
        if action == "unload":
            runtime.unload(plugin_id)
            return
        inst = self._host.registry.get(plugin_id)
        if inst is None:
            log.warning("Reloader: plugin %s não está no registry", plugin_id)
            return
        runtime.unload(plugin_id)
        errs = runtime.load(inst)
        for e in errs:
            log.warning("Plugin %s ao recarregar: %s", plugin_id, e)


def _plugin_session_status_for(is_working: bool, is_running: bool) -> str:
    """Mapeia o estado interno (working/running) pros status da spec.

    Tabela:
    - running + working → 'running'
    - running + idle    → 'awaiting-input'
    - !running          → 'completed'
    """
    if not is_running:
        return "completed"
    return "running" if is_working else "awaiting-input"
