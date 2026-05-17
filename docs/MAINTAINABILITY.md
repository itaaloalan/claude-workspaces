# Análise de Manutenibilidade — claude-workspaces

Consolidado de 4 agentes independentes (arquitetura, complexidade UI, testabilidade,
tech debt). Última varredura: 2026-05-15. Última atualização: 2026-05-17.

Itens marcados ✓ já foram resolvidos; ✗ pendentes.

---

## 🚨 Críticos (vão estourar com 2-3× mais código)

### 1. `main_window.py` é God Object  ✓
- Era 1689 linhas no início desta passada; hoje ~1376 mesmo com a feature
  nova de tray/notificações nativas integrada em paralelo.
- Extraídos:
  - `ui/builders/terminal_pane_builder.py` (`_build_terminal_pane`)
  - `ui/builders/sidebar_builder.py` (`_build_sidebar`)
  - `ui/builders/shortcuts_installer.py` (`install_shortcuts`)
  - `ui/coordinators/plugin_coordinator.py` (~200 linhas de wiring de plugin host)
  - `ui/session_export_dialog.py` (`_export_session`)

### 2. State global crescendo sem invalidação  ✓
- `TerminalState` (`ui/terminal_state.py`) ganhou `tab_workspaces` (mapping
  tab_id → workspace_id) e `release_workspace(workspace_id)` pra cleanup
  em bloco.
- `TerminalCoordinator.cleanup_area` chama `release_workspace` e re-emite
  `tab_removed` — defensivo contra qualquer caminho onde `close_all` não
  tenha disparado o sinal normal.

### 3. Tratamento de exceção inconsistente  ✓
- Novo `logging_utils.py` com decorator `@log_exceptions(message=, default=, reraise=)`.
- Aplicado em handlers de signal/timer críticos (`_persist_layout`,
  `_persist_active_sessions`, `_restore_sessions`).
- `claude_activity.py` agora loga em vez de silenciar decode (era dead code
  com `errors="replace"`, mas serve como diagnóstico se a contract mudar).

---

## ⚠️ Altos (limitam evolução, ainda não quebram)

### 4. CSS inline em 15 arquivos  ✓ (theme.py extraído)
- 42 ocorrências de `#3d6ea8` (azul primário) + `#4a82c5` (hover) + `#2a2a2a`.
- Cada arquivo reinventa estilo de botão/splitter/border.
- **Resolvido:** `ui/theme.py` centraliza paleta + helpers de QSS.

### 5. Painéis sem contrato comum  ✓
- `ui/panels/base.py` define `DockPanel` Protocol (runtime_checkable) +
  `DockPanelSpec` dataclass. `MainWindow.DOCK_PANEL_SPECS` é fonte única
  de verdade pros painéis carregados.

### 6. UI conhece subprocess/git/storage direto  ✓
- `git_panel._head_sha` (último `subprocess.run` na UI) migrou pra
  `git_actions.head_sha`.
- `main_window._launch_claude_for` já delegava pro `LaunchCoordinator` +
  `launch_planner` (sem subprocess direto).

### 7. Módulos críticos sem teste  ✓
- Testes adicionados: `test_launchers.py` (11), `test_claude_sessions.py` (19),
  `test_pty_session.py` (9), `test_hook_manager.py` (10), `test_logging_utils.py` (4),
  `test_session_persistence.py` (9). Total: **443 testes** (era 368).
- Coverage geral: 32% (puxa pra cima rodando os módulos UI no headless).

---

## 🟡 Médios (limpeza vale)

### 8. Dead code: `CollapsiblePanel`  ✓ (removido)
- Arquivo deletado.

### 9. 9 imports tardios em `main_window.py`  ✓
- Movidos pro topo: `QInputDialog`, `QGuiApplication`, `QBrush/QColor`,
  `QAction`, `QMenu`, `ShortcutsDialog`, `LaunchClaudeDialog` (re-export pra
  tests), `find_files`, `open_in_file_manager`, `list_sessions_for_paths`,
  `open_path_in_editor`.

### 10. Magic numbers espalhados  ✓
- `ui/theme.py` ganhou seção "Tempos (ms)" e "Dimensões (px)":
  `LAYOUT_SAVE_DEBOUNCE_MS`, `SPINNER_INTERVAL_MS`, `AUTOSAVE_INTERVAL_MS`,
  `GIT_POLL_INTERVAL_MS`, `REMINDER_TICK_MS`, `SPLITTER_HANDLE_W`,
  `SIDEBAR_DEFAULT_W`, `TERMINAL_HEADER_MIN_H`, `TERMINAL_BTN_W`, etc.
- Aplicados em `main_window`, `terminal_pane_builder`, `memory_panel`.

### 11. Lambdas capturando widgets  ✓
- `skills_panel.py` — singleShot lambda agora captura `row: int`, não o
  `QListWidgetItem`. Novo `_restore_item_text(row, text)` valida antes de tocar.
- `terminal_area.py` — lambdas com `w=widget` são sender-bound; Qt
  auto-disconnect quando o sender é destruído. Padrão seguro, mantidas.

### 12. CI sem lint/mypy/coverage  ✓
- `pyproject.toml` ganhou config de `mypy` + `coverage` + dev deps
  (`pytest-cov`, `mypy`).
- Workflow CI ganhou job `mypy` (não-bloqueante, reporta sem failar) e
  step `pytest --cov` com upload do `coverage.xml` como artifact.
- Mypy hoje: 76 issues (mapeadas pra cleanup futura).

---

## Ordem de ataque (histórico)

| # | Ação | Esforço | Status |
|---|------|---------|--------|
| 1 | Remover `collapsible_panel.py` | 5 min | ✓ |
| 2 | Extrair `theme.py` com paleta + helpers | 1h | ✓ |
| 3 | `DockPanel` Protocol + `DOCK_PANEL_SPECS` | 2h | ✓ |
| 4 | `services/launch_planner.py` extraído | 2h | ✓ |
| 5 | `TerminalState` com ciclo de vida | 3h | ✓ |
| 6 | Testes de 9 módulos puros (122 testes total) | 4h | ✓ |
| 7 | CI: `ruff` no workflow + config em pyproject | 30 min | ✓ |
| 8 | Builders + PluginCoordinator (main_window 1689→1376) | 4h | ✓ |
| 9 | TerminalState.release_workspace | 1h | ✓ |
| 10 | @log_exceptions decorator + aplicação | 1h | ✓ |
| 11 | head_sha movido pro git_actions | 30 min | ✓ |
| 12 | Testes de launchers/claude_sessions/pty_session/hook_manager | 3h | ✓ |
| 13 | Magic numbers → theme.py constants | 1h | ✓ |
| 14 | Lambdas auditadas / corrigidas | 30 min | ✓ |
| 15 | CI mypy + coverage | 30 min | ✓ |

## Próximas direções (não-críticas)

- Reduzir 76 issues de mypy gradualmente — começar por módulos puros que
  já têm cobertura de teste.
- Migrar QSS hardcoded restante (memory_panel ainda tem CSS inline mesmo
  com theme.py).
- Persistência de tabs Claude entre execuções (✓ — `session_persistence.py`).
- Atalho global via systemd unit (✓ — `packaging/install-systemd.sh`).
- MCPs além do postgres (✓ — API genérica + presets em `mcp_manager.py`;
  falta refletir na UI do MCP dialog).
