# Changelog

Todas as mudanças relevantes neste projeto são documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto segue [versionamento semântico](https://semver.org/lang/pt-BR/) pragmático
(pré-1.0: `minor` para features visíveis, `patch` para correções/refactors).

## [0.7.5] — 2026-05-18

### Adicionado
- **Toolbar de ações em todo terminal**: os atalhos que antes só
  apareciam no menu de contexto da sidebar (Continuar / Ciclar modo /
  Trocar effort / Trocar modelo) agora ficam visíveis como botões no
  topo de cada console Claude. Substitui o antigo botão único `⚙ Modo`
  que abria um popup — clique direto faz a ação sem intermediário.
- **Toggle global "⌃ Ações"** na top bar (logo após "Claude Workspaces")
  pra ocultar/mostrar essa toolbar em todos os terminais de uma vez. O
  estado é persistido em `show_terminal_actions` nas settings. Mesmo com
  a toolbar oculta, as ações continuam acessíveis pelo menu de contexto
  da sidebar (clique direito no item do console).
- **Botões inline em cada workspace na sidebar**: ＋ (abre um Claude
  novo no workspace, mesma ação de "Abrir Claude") e ▾/▸ (recolhe ou
  expande os filhos do workspace na tree). O ícone do botão de
  colapsar sincroniza com o disclosure triangle nativo da árvore.

## [0.7.4] — 2026-05-18

### Adicionado
- **Textos das notificações configuráveis** em Configurações → Notificações.
  Antes os títulos vinham fixos (`✅ Pronto`, `🔁 Ainda aguardando`,
  `Claude Workspaces` como app_name, `Claude — {project}` no hook Stop),
  o que deixava banners genéricos no centro de notificações — um popup
  só com "Claude Code" no topo não dizia qual workspace tinha terminado.
  Cinco campos novos:
  - **Nome do app**: usado no app_name do D-Bus, tooltip do tray e flag
    `-a` do `notify-send` do hook. Aparece como cabeçalho do popup.
  - **Prefixo 'pronto'** / **Prefixo re-lembrete**: vão antes do nome do
    workspace nos toasts emitidos pelo app. String vazia esconde o
    prefixo.
  - **Título do hook** (template, aceita `{project}`) e **body padrão
    do hook**: usados pelo `notify-hook.py` quando o Stop event dispara.
    Como o hook roda como subprocess separado do Claude Code, ele relê
    as settings de `~/.config/claude-workspaces/settings.json` a cada
    turno.
  Salvar Configurações recria o `DesktopNotifier` no ato pra que o
  `app_name` novo já valha pra próxima notificação (não dá pra mudar
  esse campo num notifier vivo via D-Bus).

## [0.7.3] — 2026-05-18

### Corrigido
- **Crash ao terminal mudar de estado running** (`AttributeError:
  'QTreeWidget' object has no attribute 'count'`): `_refresh_item_label`
  e `_search_submit` ainda usavam a API antiga de `QListWidget`
  (`count()`, `item(i)`, `setCurrentRow()`) depois da migração da
  sidebar pra `QTreeWidget`. Agora reusam `_find_workspace_item` e
  `topLevelItem(...)` corretamente, evitando a exceção a cada
  notificação de `running/idle` vinda do PTY.

## [0.7.2] — 2026-05-18

### Corrigido
- **Flicker de "Ocioso" durante o turno do Claude**: o parser de
  `claude_activity` oscila entre `is_working=True/False` enquanto o
  Claude alterna entre tool calls e geração de texto, fazendo o status
  na sidebar piscar "Trabalhando ↔ Ocioso". Agora a transição
  working→idle é debounced — só vira "Ocioso" se ficar N segundos
  estável sem voltar a working. Working→awaiting (`needs_decision`)
  continua imediato, pra não atrasar o feedback de permission prompts.

### Adicionado
- **Setting global `idle_debounce_seconds`** (default **20s**, range
  0–120s) na seção "Detecção de status" da tela de Configurações.
  Controla o debounce acima. Aplicado a todos os terminais vivos
  imediatamente após salvar (via class-attr em `TerminalWidget`,
  sem precisar reiniciar). 0 desliga o debounce (volta ao
  comportamento antigo, com flicker).
- **Janela de graça pós-startup (3s)** no `TerminalWidget`: nos
  primeiros 3 segundos depois do PTY entrar em running, o debounce
  working→idle é ignorado. Fecha o caso "reabri o app com sessões
  já no prompt principal e fiquei 20s vendo 'Trabalhando' até virar
  'Ocioso'" — agora vira "Ocioso" assim que o parser confirma o
  marker idle, sem esperar o debounce.

## [0.7.0] — 2026-05-18

### Adicionado
- **Botão "⚙ Modo"** na toolbar de cada terminal Claude, ao lado de
  ▶ Continuar / Encerrar. Abre um popup estilo VS Code com:
  - Os 5 modos do Claude Code (Ask before edits / Edit automatically /
    Plan / Auto / Bypass permissions) descritos um por um. Clique em
    qualquer linha = manda `Shift+Tab` no PTY (cicla pro próximo modo).
  - "Trocar effort" — abre `/effort` no prompt.
  - "Trocar modelo" — abre `/model` no prompt.
- **Infos da sessão no menu de contexto da sidebar**: clique direito num
  console mostra modelo da última mensagem assistant, total de tokens
  (in/out/cache) e custo aproximado em USD — lidos do JSONL claimed em
  `~/.claude/projects/`. Embaixo das infos, mesmos atalhos do popup:
  Continuar / Ciclar modo / Trocar effort / Trocar modelo.
- **Probe de versão do Claude Code no startup** (`claude_probe.py`):
  roda `claude --version`, parseia e loga se está fora do range testado
  (`TESTED_CLAUDE_RANGE` — hoje `2.1.0`–`2.1.999`). Não bloqueia. Útil
  pra explicar regressões depois de auto-updates do Claude Code que
  mudem schema dos JSONLs, copy do TUI ou slash commands.

### Mudado
- `usage_telemetry.UsageStats` ganhou campo `last_model` — reflete o
  modelo da última mensagem assistant (acompanha `/model` mid-session).
- `usage_telemetry.usage_for_session(jsonl_path)` novo helper —
  agrega tokens/custo de **uma** sessão sem varrer todos os projetos.
- `TerminalWidget.claimed_session_path()` exposto pro menu de contexto
  conseguir ler o JSONL da sessão claimed.

## [0.6.0] — 2026-05-18

### Adicionado
- **Favoritar sessão (★)** no card de cada sessão recente: clique na estrela
  marca/desmarca a sessão como favorita. Persiste em
  `~/.config/claude-workspaces/session_marks.json` (não mexe nos arquivos do
  Claude Code em `~/.claude/projects/`).
- **Filtro "só favoritas"** no header de Sessões recentes (botão ★ ao lado do
  campo de busca). Combina com o filtro de texto.
- Sessões favoritadas são **sempre carregadas**, mesmo que estejam fora das 20
  mais recentes — fecha o caso "marquei pra achar depois e a sessão envelheceu".
- Novo módulo `session_marks` com API `is_starred / set_starred / starred_ids`.
  A estrutura do JSON já reserva campos `tags` e `note` pra evolução futura
  (tags nomeadas, anotações livres) sem precisar migrar formato.

### Corrigido
- Filtro de texto da lista de Sessões recentes estava parcialmente quebrado:
  o `QListWidgetItem` não armazenava o `ClaudeSession` em `UserRole`, então
  digitar qualquer coisa escondia todos os cards em vez de buscar pelo preview.
  Agora o `UserRole` é populado e a busca por texto realmente filtra.

## [0.5.1] — 2026-05-18

### Adicionado
- Botão **"▶ Continuar"** na toolbar de cada terminal: manda `continue` + Enter
  pro Claude com um clique. Resolve o caso de reabrir o app com várias sessões
  retomadas e ter que digitar manualmente em cada uma pra elas voltarem a
  trabalhar.
- **Menu de contexto na sidebar** (botão direito) com:
  - "▶ Continuar este console" em cima de uma aba de terminal Claude.
  - "▶ Continuar todos os consoles deste workspace" em cima do nome do workspace
    — manda `continue` em rajada pra todos os consoles vivos daquele workspace.
- Botão **"esconder tudo"** (▸) no topo do strip do dock direito: fecha todos
  os painéis abertos de uma vez (Git/Memória/Skills). Quando todos fechados,
  o strip continua visível com os ícones pra reabrir.

### Mudado
- **Activity bar** (à esquerda) reestilizada: glyphs Unicode monocromáticos
  (❒/☰/⚓/⌬/◆/▣/⚙) no lugar dos emojis coloridos; presentation selector
  U+FE0E + font-stack `Symbola/DejaVu`/etc forçam renderização de "ícone
  técnico" em vez de "emoji infantil". Hover/checked migrados pra paleta
  do `theme.*`.
- **Dock direito** com botões de painel mais limpos: ícones glyph (⎇ Git,
  ❏ Memória, ✦ Skills) com tooltip no lugar do texto rotacionado, paleta
  unificada via `theme.*`, strip um pouco mais largo (32→36px) pra acomodar
  os glyphs com folga.
- `DockPanelSpec` ganhou campo `icon` opcional pra o glyph exibido no strip.

## [0.5.0] — 2026-05-18

### Adicionado
- Exibição da versão atual na sidebar, logo abaixo do botão "🔧 Hack este app".
- Diálogo de release notes ao clicar na versão: mostra o que mudou na versão atual
  e o histórico completo de versões anteriores (parseado deste `CHANGELOG.md`).
- Subsistema de **plugins** completo: spec v1.0, loader, validador, registry, runtime
  Python com `ctx.workspaces`/`ctx.sessions`/`ctx.fs`/`ctx.http`, 6 eventos com timeout,
  paleta de comandos (Ctrl+P), view top-level Plugins (🧩 Ctrl+5), tela de detalhe
  em PT-BR, configurações inline com auto-save, botão "Exemplos" instalando bundles
  do repo, botão pra solicitar criação de novo plugin via Claude, card amigável de
  onboarding e 4 exemplos prontos (commit-coach, idle-rescue, focus-timer,
  workspace-snapshot).
- View **Apps** (🧰 Ctrl+Shift+6) com PWAs embutidos via QtWebEngine.
- Notificações nativas via D-Bus com botões de ação (Abrir/Adiar/Já vi), tray nativo,
  re-lembretes da inbox e claim de sessão por aba.
- Restaurar abas Claude ativas ao reabrir o app.
- Detecção de PR existente: abre direto no navegador com busy state, ou cria um novo
  via `gh` CLI a partir do painel Git.
- Estado **"Aguardando"** na sidebar (decisão pendente), separado de **"Ocioso"**
  (no prompt). Detecta também pickers interativos ("Enter to select…").
- Handoff entre consoles com briefing rico e prompt-ready, detectando Claude antes
  de colar.

### Mudado
- Painel de detalhe dos plugins agora rola em vez de comprimir conteúdo.
- Sidebar foca aba ativa com clique simples (em vez de duplo).
- Card de sessão mais compacto.
- Paleta de comandos dos plugins migrou de `Ctrl+P` pra `Ctrl+Shift+P` (convenção
  VS Code; `Ctrl+P` volta a abrir Quick Open de arquivo).
- Tooltips do activity bar corrigidos pra refletir `Ctrl+Shift+1..6`.
- Documentação (README/USAGE/DEVELOPMENT) atualizada cobrindo plugins, apps, notif
  nativas e session restore.
- **Sidebar de workspaces** repaginada: cabeçalho "WORKSPACES" com caps/letter-spacing
  e borda inferior sutil; seleção mais suave (tint azul + borda lateral em vez de
  bloco saturado); hover discreto; nomes de workspace em negrito pra hierarquia
  clara; linha "↻ última sessão" em itálico/menor/muted; botão "+ Novo Workspace"
  reestilizado como ação primária neutra; "🔧 Hack este app" agora é ação ghost.
- Linhas de console na sidebar mais compactas (48px → 42px) com estado e última
  ação na mesma sublinha separadas por ponto, paleta unificada via `theme.*`.

### Corrigido
- Consoles vivos somem da sidebar quando workspace tem child "↻ histórica".
- Título de sidebar desambiguado quando dois Claudes começam com o mesmo prompt.
- Actions clicadas pela central do Plasma 6 não disparavam callback.
- Banners "✅ Pronto" espúrios durante extended thinking / tool runs lentas
  (working↔idle flipping no parser de atividade).
- Notificações D-Bus empilhando ao receber re-lembrete + banner stale após o
  Claude voltar a trabalhar (usa `replaces_id` e fecha proativamente quando o
  tab sai da inbox).
- Atalho `Ctrl+P` estava bound duas vezes — abria a paleta de plugins em vez
  do Quick Open de arquivo.
- Limpa botões fantasmas ao trocar de plugin selecionado.
- Ignora `__pycache__` silenciosamente na validação do bundle de plugins.

## [0.4.0] — 2026-02-12

### Adicionado
- **Activity bar** vertical à esquerda + views top-level pra Catálogo, Hooks, MCP
  e Settings (Ctrl+Shift+1..6).
- Catálogo navegável de skills/agents/commands.
- Inspectores visuais de hooks e MCP, com editor e playground.

### Mudado
- Refactor `PR1`: 4 coordinators extraídos do `MainWindow`.
- Refactor `PR2`: `errors.py` + logs nos `except` críticos.
- Refactor `PR3`: zero `subprocess` direto na camada UI.
- Esconde tarefas concluídas da sidebar (mantém em sessões recentes).

### Corrigido
- Terminal maximiza/aumenta mesmo com Settings aberto.
- Minimizar terminal mantém barra do título visível.
- Detecção positiva de "working" evita "Trabalhando" grudado.
- Resize pós-fork pra Claude usar largura total do terminal.

## [0.3.0] — 2025-12-02

### Adicionado
- **Telemetria de skills** (uso e último-lido das sessões do Claude).
- **Busca full-text** nas sessões (Ctrl+Shift+F).
- **Telemetria de uso/custo** — tokens e $ estimado inline.
- **Templates de workspace** — bundled + custom JSONs.
- Overrides per-workspace pros defaults de git/worktree.
- "Criar nova branch" habilitada sem worktree (git checkout -b in-place).
- Auto-resume da última sessão (Ctrl+Shift+R) + export markdown da sessão.

### Mudado
- `DockPanel` Protocol + `DOCK_PANEL_SPECS` (manutenibilidade #3).
- `TerminalState` concentra os 4 dicts soltos (manutenibilidade #5).
- `services/launch_planner` extraído (manutenibilidade #4).
- Testes pra 7 módulos puros + ruff no CI.

### Corrigido
- "Criar nova branch" ficava trancado + `right_splitter` sem snap.

## [0.2.0] — 2025-10-15

### Adicionado
- **Painel Git** como terceira coluna — branch, status, double-click abre no editor.
- Diff inline + ações git (checkpoint estilo IntelliJ).
- Context menu do Git (Add upfront, Stage/Unstage/Rollback/Delete).
- **Dock direito** estilo IntelliJ — tool strip vertical com botões rotacionados.
- Sidebar `QTreeWidget` — workspaces com children mostrando consoles ativos.
- Filtros Skills/Agents/Comandos + child widget rico + filtro de sessões em tempo real.
- Inbox global de consoles aguardando atenção — bell no topbar.
- Painel **Memória** — editor do `CLAUDE.md` da pasta primária no dock.
- Worktree opcional ao abrir Claude — checkbox no `LaunchClaudeDialog`.
- Tree mostra título da sessão Claude (1º prompt), tooltip com texto completo.
- Checkbox de pastas + criar/usar branch existente no launch dialog.
- Handoff entre consoles + configs gerais de worktree.

### Mudado
- App-wide dark palette + Fusion style (Breeze do KDE ignorava QSS).
- `theme.py` centraliza paleta + helpers.
- Resize com debounce do refit + queue cancel no JS.

### Corrigido
- `launch_paths` nunca colapsa pro pai comum.
- Double-click no tree de sessão abria Konsole externo.
- Parser de atividade ignora footer + ANSI strip mais robusto.

## [0.1.0] — 2025-08-20

### Adicionado
- Esqueleto inicial em PySide6.
- Sidebar de workspaces, launchers de IDE, aba de Settings e botão de self-dev
  ("🔧 Hack este app").
- Logging, instalador `.desktop` e manuais de uso/dev.
- **Terminal embutido** com xterm.js + pty no painel direito.
- Abas de terminal por workspace + retomar sessões do Claude.
- Notificações via hook `Stop` do Claude + sessões multi-folder.
- Badge de workspace rodando + busca na sidebar.
- Refactor de layout — topbar global, terminal full-width, tarefas e cards.
- AUR `PKGBUILD` + correções UX no layout.
- Sessão→tarefa, atalhos de workspace, drag-drop de pastas, estado da aba.
- Busca por tarefas + Enter pra primeiro match + testes + CI.
- Terminal confinado ao painel direito + botões maximizar/minimizar.
- Filtros Pendentes/Concluídas/Todas no painel de Tarefas.
- Gerenciar MCP postgres por workspace + fix init dos chips.

### Corrigido
- Usar shell de login (`/etc/passwd`) em vez de `$SHELL` pra resolver aliases.
- Enviar bytes crus do pty como `QByteArray` pra preservar UTF-8.
- Usar pai comum como cwd quando todas as pastas são irmãs.
- Cores explícitas na lista de tarefas (texto invisível em tema dark).
