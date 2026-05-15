# Análise de Manutenibilidade — claude-workspaces

Consolidado de 4 agentes independentes (arquitetura, complexidade UI, testabilidade,
tech debt). Última varredura: 2026-05-15.

Itens marcados ✓ já foram resolvidos; ✗ pendentes.

---

## 🚨 Críticos (vão estourar com 2-3× mais código)

### 1. `main_window.py` é God Object  ✗
- 1248 linhas, 70 métodos, 7 funções > 40 linhas.
- Orquestra: layout, sidebar, terminal, dock, inbox, atalhos, persistência,
  launch flow, git, edição, CRUD de workspaces.
- 7 candidatos a extração:
  - `_build_ui` (105 linhas) → `_setup_terminal_buttons`, `_setup_splitters`
  - `_build_terminal_pane` (65) → `TerminalPaneBuilder`
  - `_build_sidebar` (57) → `SidebarBuilder`
  - `refresh_list` (73) → `_rebuild_terminal_tree_items`
  - `_on_tab_activity` (47) → mistura cache, spinner, inbox
  - `_quick_open_file` (44) → dialog + subprocess + pattern search
  - `_launch_claude_for` (55) → worktree + dialog + terminal creation

### 2. State global crescendo sem invalidação  ✗
- `_terminal_tree_items: dict[int, QTreeWidgetItem]`
- `_terminal_activity: dict[int, tuple[str, bool, str]]`
- `_inbox: dict[int, dict]`
- Limpeza só em `_on_tab_removed`. Se um tab fechar sem disparar, vaza.
- **Ação:** extrair `TerminalState` com cleanup automático por workspace_id.

### 3. Tratamento de exceção inconsistente  ✗
- `pty_session.py:56` — `except Exception: os._exit(127)` sem log.
- `claude_activity.py:51` — `except Exception: return Activity(...)` mudo.
- `launch_claude_dialog.py:111` — `except Exception: self.path_preview.setText("...")`.
- Mistura: `log.exception()`, `bare except`, `QMessageBox`, `silent` em vários paths.
- **Ação:** decorator `@log_exceptions` + convenção: sempre `log.exception` + contexto.

---

## ⚠️ Altos (limitam evolução, ainda não quebram)

### 4. CSS inline em 15 arquivos  ✓ (theme.py extraído)
- 42 ocorrências de `#3d6ea8` (azul primário) + `#4a82c5` (hover) + `#2a2a2a`.
- Cada arquivo reinventa estilo de botão/splitter/border.
- **Resolvido:** `ui/theme.py` centraliza paleta + helpers de QSS.

### 5. Painéis sem contrato comum  ✗
- `GitPanel`, `SkillsPanel`, `MemoryPanel` repetem `set_workspace()` sem interface.
- `RightDock` é só layout, não coordena estado.
- **Ação:** criar `ui/panels/base_panel.py` com `class DockPanel(QWidget)` Protocol.

### 6. UI conhece subprocess/git/storage direto  ✗
- `main_window._launch_claude_for` chama `add_worktree` direto.
- `git_panel._do_commit` faz `subprocess.run(["git", "reset", ...])`.
- **Ação:** extrair `services/launcher_service.py`, `services/git_operations.py`.

### 7. Módulos críticos sem teste  ✗
- Sem testes: `git_actions.py` (99 linhas), `launchers.py` (135),
  `git_worktree.py` (110), `claude_sessions.py` (127),
  `skills_discovery.py` (256), `claude_activity.py` (75),
  `pty_session.py` (125), `hook_manager.py` (169).
- **Ação rápida:** `test_claude_activity.py` + `test_git_actions.py` cobrem
  bem 175 linhas de lógica pura.

---

## 🟡 Médios (limpeza vale)

### 8. Dead code: `CollapsiblePanel`  ✓ (removido)
- 106 linhas, não importado depois do refactor pro `RightDock`.
- **Resolvido:** arquivo deletado.

### 9. 9 imports tardios em `main_window.py`  ✗
- `QInputDialog`, `QGuiApplication`, `ShortcutsDialog`, `QColor/QPalette`,
  `LaunchClaudeDialog`, `add_worktree`, `open_path_in_editor`, etc.
- Cheiro de circular dep ou refactor incompleto.
- **Ação:** mover pro topo do arquivo (se não houver ciclo).

### 10. Magic numbers espalhados  ✗
- `600ms` (layout save), `100ms` (spinner), `8px` (splitter), `260px` (sidebar),
  `420px` (right split), `3000ms` (auto-save), `30_000ms` (git poll), `28px`
  (button width).
- **Ação:** mover pra `ui/theme.py` ou constants.

### 11. Lambdas capturando widgets  ✗
- `skills_panel.py:235` — `QTimer.singleShot(lambda i=item: ...)`. Se item
  morrer antes do timer, crash.
- `terminal_area.py:35/38/41` — `lambda running, w=widget: ...`.
- **Ação:** auditar; usar `functools.partial` ou method refs.

### 12. CI sem lint/mypy/coverage  ✗
- Só roda pytest.
- **Ação:** `ruff check`, `mypy`, `coverage report` em `.github/workflows/test.yml`.

---

## Ordem de ataque

| # | Ação | Esforço | Status |
|---|------|---------|--------|
| 1 | Remover `collapsible_panel.py` | 5 min | ✓ |
| 2 | Extrair `theme.py` com paleta + helpers | 1h | ✓ |
| 3 | `BasePanel` Protocol + adaptar panels | 2h | ✗ |
| 4 | `services/launcher_service.py` extraído | 2h | ✗ |
| 5 | `TerminalState` com ciclo de vida | 3h | ✗ |
| 6 | Testes de `git_actions`, `claude_activity`, `skills_discovery` | 4h | ✗ |
| 7 | CI: `ruff` + `mypy` | 30 min | ✗ |
