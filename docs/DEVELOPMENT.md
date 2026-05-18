# Manual de desenvolvimento

## Setup

```bash
git clone https://github.com/itaaloalan/claude-workspaces.git
cd claude-workspaces

python -m venv .venv
.venv/bin/pip install -e ".[dev]"   # inclui pytest + ruff
.venv/bin/claude-workspaces

# Testes
.venv/bin/python -m pytest -q

# Lint
.venv/bin/ruff check src/ tests/
```

Python 3.11+ é obrigatório (uso de `match`, `int | None`, etc.).

## Estrutura

```
src/claude_workspaces/
├── app.py                  # entrypoint da QApplication (paleta + Fusion style)
├── __main__.py
├── models.py               # Workspace dataclass (overrides per-workspace)
├── storage.py               # leitura/escrita de workspaces.json
├── settings.py              # Settings dataclass + persistência
├── stacks.py                # detecção Java/Web/Python/C#
├── launchers.py             # launchers externos (Konsole, IDEs)
├── logging_setup.py
├── logging_utils.py         # decorator @log_exceptions pra handlers Qt
├── errors.py                # LaunchError + tipos de erro do domínio
├── briefing_builder.py      # monta briefing de handoff (sem Qt)
├── claude_activity.py       # parser puro do output do pty (status + working)
├── claude_sessions.py       # leitura dos JSONLs em ~/.claude/projects/
├── session_persistence.py   # save/restore das abas Claude ativas
├── git_actions.py           # subprocess: stage, unstage, commit, checkout, discard
├── git_status.py            # subprocess: branch, ahead/behind, porcelain
├── git_worktree.py          # worktree add/remove + list_local_branches
├── pr_actions.py            # gh push + gh pr create (subprocess)
├── pr_draft.py              # gera título/corpo do PR a partir do diff
├── pr_provider.py           # detecta o que está disponível (gh, branch, remote)
├── hook_manager.py          # instala/remove hook Stop em ~/.claude/settings.json
├── mcp_manager.py           # CRUD do MCP postgres em ~/.claude.json (com backup)
├── pty_session.py           # QObject que executa pty.fork e emite output_received
├── sessions_search.py       # busca full-text nas sessões antigas
├── skills_discovery.py      # varre skills/agents/commands (user+plugin+project)
├── skills_lint.py           # avisos sobre frontmatter mal formado
├── skills_telemetry.py      # agrega uso de Skills lendo tool_use dos JSONLs
├── usage_telemetry.py       # agrega tokens/custo por workspace
├── workspace_templates.py   # templates bundled + custom JSON
├── plugin_api.py            # API exposta aos plugins (run_in_terminal, notify, ...)
│
├── plugins/                 # subsistema de plugins (manifest v2 — ver PLUGIN_SPEC.md)
│   ├── manifest.py          # dataclass Manifest + ConfigField + Permission
│   ├── manifest_loader.py   # parse de plugin.yaml + validações
│   ├── bundle_validator.py  # rejeita bundle inválido antes de instalar
│   ├── static_analyzer.py   # AST scan: import proibido, syscall, etc
│   ├── registry.py          # CRUD de plugins instalados
│   ├── storage.py           # paths em ~/.config/claude-workspaces/plugins/
│   ├── config_store.py      # config per-plugin (auto-save)
│   ├── runtime.py           # subprocess host (entrypoint + isolation)
│   ├── events.py            # dispatch dos eventos do app pros plugins
│   ├── semver.py            # versão compat checks
│   └── errors.py            # RegistryError / ValidationError
│
├── services/               # lógica de negócio extraída da UI (sem Qt — ou só QObject leve)
│   ├── launch_planner.py    # plan_from_dialog, build_claude_argv
│   ├── desktop_notifier.py  # FDO Notifications via gdbus + QtDBus (sinais)
│   ├── hooks_inspector.py   # agrega hooks de ~/.claude/settings.json + projects
│   ├── mcp_inspector.py     # snapshot dos MCP servers configurados
│   ├── plugin_host.py       # bridge UI ↔ plugins/runtime
│   ├── quick_open.py        # `git ls-files` matcher (Ctrl+P, "em breve")
│   ├── session_export.py    # dump da sessão JSONL pra md/json
│   ├── skills_install.py    # download/instala skills de URL
│   └── system_open.py       # xdg-open wrappers
│
└── ui/
    ├── main_window.py            # QMainWindow + activity bar + body_splitter + dock
    ├── activity_bar.py           # coluna vertical de views top-level (VS Code-style)
    ├── theme.py                  # paleta + helpers de QSS (centralizado)
    ├── top_bar.py                # logo + busca + inbox bell + Configurar
    ├── right_dock.py             # tool strip vertical + QSplitter (panels)
    ├── terminal_state.py         # estado per-tab agregado (TerminalState)
    ├── terminal_widget.py        # 1 aba: pty + xterm.js via QWebEngineView
    ├── terminal_area.py          # QTabWidget que agrupa abas de um workspace
    ├── terminal_child_widget.py  # widget rich pros children do sidebar tree
    ├── workspace_details.py      # painel central (Sessões, ações, MCP, uso)
    ├── workspace_dialog.py       # criar/editar workspace (com overrides)
    ├── launch_claude_dialog.py   # antes de cada Abrir Claude (pastas + worktree)
    ├── handoff_dialog.py
    ├── settings_panel.py
    ├── memory_panel.py           # editor de CLAUDE.md
    ├── skills_panel.py           # lista Skills/Agents/Commands com filtros
    ├── skill_detail_dialog.py    # detalhe modal (uso no dock)
    ├── skill_detail_view.py      # detalhe embedded (uso no Catálogo)
    ├── skill_editor_dialog.py    # editor do frontmatter + body
    ├── skill_playground_dialog.py
    ├── git_panel.py              # tree IntelliJ-style + commit area
    ├── open_pr_dialog.py         # título/corpo do PR antes do gh pr create
    ├── mcp_dialog.py
    ├── mcp_explorer_dialog.py    # (substituído pela MCP view, mas ainda usado)
    ├── hooks_inspector_dialog.py # (substituído pela Hooks view, ainda usado)
    ├── plugin_palette_dialog.py  # Ctrl+P → comandos dos plugins
    ├── new_plugin_request_dialog.py
    ├── session_card.py
    ├── session_export_dialog.py
    ├── sessions_search_dialog.py
    ├── shortcuts_dialog.py
    │
    ├── views/                    # views top-level (substituem o painel central)
    │   ├── apps_view.py           # PWAs via QtWebEngine (perfil isolado)
    │   ├── catalog_view.py        # skills + detalhe split
    │   ├── hooks_view.py          # hooks inspector full-width
    │   ├── mcp_view.py            # MCP servers full-width
    │   └── plugins_view.py        # plugins instalados + detalhe
    │
    ├── coordinators/             # extraídos do MainWindow (sem widgets, só lógica)
    │   ├── dock_coordinator.py
    │   ├── launch_coordinator.py
    │   ├── plugin_coordinator.py
    │   ├── terminal_coordinator.py
    │   └── workspace_coordinator.py
    │
    ├── builders/                 # construção de partes pesadas do MainWindow
    │   ├── shortcuts_installer.py # install_shortcuts(mw)
    │   ├── sidebar_builder.py
    │   └── terminal_pane_builder.py
    │
    ├── panels/
    │   └── base.py               # DockPanel Protocol + DockPanelSpec
    │
    └── static/
        ├── terminal.html
        ├── terminal.js           # xterm.js wiring + fit aggressivo
        └── vendor/               # xterm.js + fit addon (vendoreado, sem CDN)

tests/                      # pytest, 549 testes (lista atualizada via `ls tests/`)
packaging/aur/              # PKGBUILD + .SRCINFO pro AUR
docs/                       # USAGE, DEVELOPMENT, MAINTAINABILITY, PLUGIN_SPEC, DISTRIBUTION
```

## Arquitetura

### Camadas

```
┌─────────────────────────────────────────────────────────┐
│ UI (ui/)                                                 │
│   MainWindow orquestra; panels seguem DockPanel Protocol │
│   Widgets puros + Qt signals; sem subprocess direto      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Services (services/)                                     │
│   launch_planner.plan_from_dialog → LaunchPlan           │
│   Sem Qt. Recebe dialog results, devolve decisões.       │
│   Worktree creator / branch checkout injetáveis.         │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Domain (raíz do package)                                 │
│   git_actions, git_worktree, git_status: wrappers de     │
│     subprocess git, retornam (ok, msg)                   │
│   skills_discovery, sessions_search, *_telemetry:        │
│     leem ~/.claude/{projects,skills,plugins}             │
│   claude_activity: parser puro do output do pty          │
│   models, storage, settings: persistência                │
└─────────────────────────────────────────────────────────┘
```

### Fluxo principal: abrir Claude

```
User click "Abrir Claude" no WorkspaceDetailsPanel
  → emite launch_claude_requested(workspace, "", "")
MainWindow._launch_claude_for:
  → cria LaunchClaudeDialog(workspace, settings)
  → coleta dialog results (folders, isolate, branch, …)
  → services.launch_planner.plan_from_dialog(...)
      ↓ se isolate: git_worktree.add_worktree
      ↓ se in-place new branch: git_actions.checkout_new_branch
      → LaunchPlan(cwd, extras, worktree_label, error)
  → services.launch_planner.build_claude_argv(...)
  → TerminalArea.add_terminal(title)
  → TerminalWidget.configure_claude(cwd, resume_id)
  → TerminalWidget.start_shell_command(argv, cwd, …)
```

### Fluxo de atividade (tempo real)

```
pty stdout → PtySession.output_received signal
  → TerminalWidget._record_output: append num buffer de 8KB
  → QTimer(250ms) chama _poll_activity
  → claude_activity.parse_status(buffer, age) → Activity(status, is_working)
  → emite activity_changed se mudou
  → TerminalArea._emit_activity (também resolve título via JSONL scan)
  → MainWindow._on_tab_activity:
      → TerminalState.update(tab_id, status, working, title)
      → atualiza TerminalChildWidget no tree (label + cor + spinner)
      → se working→idle: adiciona ao inbox + atualiza bell badge
```

### Dock panels (Protocol-based)

`ui/panels/base.py` define:

```python
@runtime_checkable
class DockPanel(Protocol):
    def set_workspace(self, workspace: Workspace | None) -> None: ...
```

Cada painel (GitPanel, MemoryPanel, SkillsPanel) satisfaz estruturalmente. MainWindow itera `self._dock_panels` em `_broadcast_workspace(ws)` — adicionar um painel novo é só estender `DOCK_PANEL_SPECS` em `main_window.py`:

```python
DOCK_PANEL_SPECS = [
    DockPanelSpec("git", "Git", lambda mw: mw.details.git_panel(), default_open=True),
    DockPanelSpec("memory", "Memória", lambda mw: MemoryPanel()),
    DockPanelSpec("skills", "Skills", lambda mw: SkillsPanel()),
]
```

## Sinais Qt → cuidado com int 32-bit

`PySide6.Signal(int, ...)` mapeia pra `int` 32-bit. Se você emitir `id(widget)` (que em 64-bit ultrapassa 2³¹), dispara `OverflowError` silencioso no handler. **Use `Signal("qint64", ...)`** quando o payload for `id()` ou outro int grande.

Ver `TerminalArea.tab_activity_changed = Signal("qint64", str, str, bool, bool)`.

## Theme (cores)

Toda paleta vive em `ui/theme.py`. Não hardcode `#3d6ea8` em widgets novos:

```python
from .theme import PRIMARY, primary_button_qss

btn.setStyleSheet(primary_button_qss())
```

Helpers disponíveis: `splitter_qss`, `primary_button_qss`, `neutral_button_qss`, `flat_icon_button_qss`, `line_edit_qss`, `chip_button_qss`, `list_widget_qss`, `tree_widget_qss`.

App-level dark palette + Fusion style são aplicados em `app.py` pra sobrescrever o tema nativo do KDE (Breeze) que ignorava QSS em alguns roles.

## Como adicionar uma stack nova (ex: Rust)

1. `stacks.py`:
   ```python
   STACK_INDICATORS["rust"] = ["Cargo.toml"]
   STACK_LABEL["rust"] = "Rust"
   STACK_TO_IDE["rust"] = "rustrover"
   ```
2. `settings.py`: adicione `rustrover_command: str = "rustrover"` + entrada em `ide_command()`.
3. `launchers.py`: `IDE_LABEL["rustrover"] = "RustRover"`.
4. `ui/settings_panel.py`: campo no form + save + refresh.

## Como adicionar uma view top-level (activity bar)

Padrão paralelo ao dock panels, mas a view ocupa a área central inteira:

1. Crie o widget em `ui/views/<minha>_view.py` (siga o padrão das existentes — toolbar + corpo).
2. Adicione constante em `ui/activity_bar.py`:
   ```python
   VIEW_MINHA = "minha"
   ```
3. Inclua a entrada no loop de botões do `ActivityBar.__init__` (ícone, id, tooltip).
4. No `MainWindow`, registre o factory da view no stack que escuta `activity_bar.view_changed` (procure `VIEW_WORKSPACES` no `main_window.py`).
5. Adicione o atalho em `ui/builders/shortcuts_installer.py`:
   ```python
   QShortcut(QKeySequence("Ctrl+Shift+7"), mw,
             lambda: mw.activity_bar.activate(VIEW_MINHA))
   ```
6. Atualize `shortcuts_dialog.SHORTCUTS` na seção "Views".

## Como adicionar um plugin

Plugins são bundles externos — o app não muda. Veja `docs/PLUGIN_SPEC.md` pra spec do manifest v2 (eventos, permissões, ConfigField).

Pra debug local:

```bash
.venv/bin/claude-workspaces  # abra a app
# View 🧩 Plugins → "Instalar de pasta" → aponta pro bundle
# Ver logs em ~/.config/claude-workspaces/plugins/<plugin>/.logs/
```

Exemplos prontos vivem em `examples/plugins/` no repo — o botão "Exemplos" dentro da view instala todos com um clique.

## Como adicionar um painel novo no dock

1. Crie o widget seguindo o Protocol `DockPanel`:
   ```python
   class MyPanel(QWidget):
       def set_workspace(self, workspace: Workspace | None) -> None:
           self.workspace = workspace
           # update internal state
   ```
2. Adicione spec em `main_window.DOCK_PANEL_SPECS`:
   ```python
   DockPanelSpec(
       panel_id="my_panel",
       title="Meu painel",
       factory=lambda mw: MyPanel(),
       default_open=False,
   )
   ```
3. O `RightDock` cria o vertical-text button no strip e o painel aparece quando o user clicar. `set_workspace` é chamado automaticamente via `_broadcast_workspace` quando o user troca de workspace.

## Como adicionar um template de workspace bundled

Edite `workspace_templates.bundled()`:

```python
WorkspaceTemplate(
    name="Minha stack",
    description="...",
    tags=["meu-tag"],
    claude_md="# Convenções\n...",
)
```

Ou usuários podem dropar JSONs em `~/.config/claude-workspaces/templates/`:

```json
{
  "name": "Time A — Python",
  "description": "Padrão da equipe",
  "claude_md": "# Conventions..."
}
```

## Testes

**549 testes** distribuídos em ~30 arquivos de teste cobrindo:

- domínio puro (activity parser, claude_sessions, sessions_search, briefing_builder, usage/skills telemetry, models, storage, settings, workspace_templates, semver dos plugins);
- subprocess wrappers (git_actions, git_status, git_worktree, hook_manager, mcp_manager, pty_session, launchers);
- services (launch_planner, mcp_inspector, hooks_inspector, skills_install, session_export);
- PR pipeline (pr_actions, pr_draft, pr_provider);
- plugins (manifest_loader, bundle_validator, static_analyzer, registry, runtime, events);
- estado de UI sem Qt (terminal_state, terminal_coordinator);
- dialogs com PySide6 instalado (skill_editor_dialog).

Ver `tests/` pra lista atual — varia conforme features novas entram.

Convenções:
- Módulos puros são testáveis sem Qt (não importar PySide6 nos tests).
- Pra testar paths em `~/.claude/`, use `monkeypatch.setattr(Path, "home", lambda: tmp_path)`.
- Pra testar git_actions/git_worktree, use fixture `repo` que faz `git init` em tmp_path.
- Pra testar `plan_from_dialog`, injete `worktree_creator` e `branch_checkout` fakes.
- Pra testar `pr_actions`, monkeypatche `subprocess.run` (não chame `gh` de verdade).
- Pra testar plugins, use fixtures de bundles válidos/inválidos em `tests/plugins/fixtures/`.

## CI (`.github/workflows/test.yml`)

- Job `lint`: roda `ruff check src/ tests/` em Python 3.12.
- Job `pytest`: matriz Python 3.11 + 3.12, instala só pytest (não instala PySide6).

## Logging

```python
import logging
log = logging.getLogger(__name__)

log.info("…")
log.exception("…")  # com traceback
```

- `RotatingFileHandler` em `~/.local/state/claude-workspaces/app.log` (~2MB, 3 backups).
- `sys.excepthook` captura unhandled.
- `qInstallMessageHandler` captura mensagens internas do Qt (avisos do QWebEngineView etc).

## Convenções

- Type hints em tudo (`list[str]`, `Workspace | None`).
- Strings de UI em PT-BR; identificadores e comentários em PT/EN misto sem regra rígida.
- Dataclasses pra modelos persistidos sempre com `from_dict`/`to_dict` tolerantes a campos ausentes (forward-compat).
- Erros nos launchers viram `LauncherError` capturado pela UI com `QMessageBox.warning`.
- Sinais Qt → pra payload grande (`id()`, etc.), use `Signal("qint64", ...)`.
- Comentário em código: **WHY**, não WHAT. Identificadores bons já explicam o que o código faz.

## Publicando uma versão

```bash
# 1. Bate versão em pyproject.toml e packaging/aur/PKGBUILD (pkgver)
# 2. Cria tag e push
git tag v0.2.0
git push --tags

# 3. Gera novo sha256 e atualiza PKGBUILD
curl -sL https://github.com/itaaloalan/claude-workspaces/archive/refs/tags/v0.2.0.tar.gz | sha256sum

# 4. Atualiza .SRCINFO
cd packaging/aur
makepkg --printsrcinfo > .SRCINFO

# 5. Sincroniza com o repo AUR (ssh://aur@aur.archlinux.org/claude-workspaces.git)
git clone ssh://aur@aur.archlinux.org/claude-workspaces.git /tmp/aur-cw
cp packaging/aur/{PKGBUILD,.SRCINFO,claude-workspaces.install,claude-workspaces.desktop} /tmp/aur-cw/
cd /tmp/aur-cw
git commit -m "v0.2.0"
git push
```

## Roadmap

Ver [MAINTAINABILITY.md](MAINTAINABILITY.md) pro status do débito técnico (todos os 7 itens concluídos atualmente). Features novas em discussão são versionadas via Issues no GitHub.

## Repo

https://github.com/itaaloalan/claude-workspaces
