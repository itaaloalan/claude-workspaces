# Manual de uso

Visão geral do que cada parte da janela faz e como usar.

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ ☰  Claude Workspaces  [busca…]                🔔  ⚙ Configurar    │  ← topbar
├────┬──────────┬──────────────────────────────────────────┬───────┤
│ 🗂 │ WORK-    │  Workspace selecionado                    │ Git   │
│ 📚 │ SPACES   │  ─ título, stack, pastas, MCP, uso (30d)  │ ····  │
│ 🪝 │          │  ─ ações (Abrir Claude / Terminal / IDEs) │       │
│ 🔌 │ ▼ ogpms  │  ─ Sessões recentes (cards)               │ Mem.  │
│ 🧩 │  ⠋ Cons1 │                                            │       │
│ 🧰 │  ❚❚ Cons2│                                            │ Skills│
│    │ ▼ map    │                                            │       │
│ ⚙  │          ├──────────────────────────────────────────┬┤       │
│    │          │ Terminal embutido (várias abas)          ││       │
│    │          │  ─ ⬇ ▢ ❐  (minimizar/maximizar/restaurar)││       │
└────┴──────────┴──────────────────────────────────────────┴───────┘
  ↑
  activity bar (views top-level)
```

- **Activity bar**: coluna vertical de ícones à esquerda — troca entre views top-level (🗂 Workspaces, 📚 Catálogo, 🪝 Hooks, 🔌 MCP, 🧩 Plugins, 🧰 Apps) e ⚙ Configurações no rodapé. Atalhos `Ctrl+Shift+1..6`.
- **Topbar**: toggle sidebar (☰), título, busca de workspaces, **bell** (consoles aguardando), Configurar.
- **Sidebar**: lista de workspaces. Cada workspace pode expandir e mostrar os consoles ativos como filhos com status colorido.
- **Centro/topo**: detalhes do workspace selecionado.
- **Centro/baixo**: terminal embutido (xterm.js + pty), com tabs por sessão.
- **Dock direito**: Git, Memória (CLAUDE.md), Skills — colapsáveis via tool strip vertical.

As views Catálogo / Hooks / MCP / Plugins / Apps ocupam a área central inteira quando ativadas (substituem temporariamente o painel de workspace + terminal).

## Criando um workspace

1. Clique **+ Novo Workspace** (sidebar) ou pressione `Ctrl+N`.
2. Opcional: escolha um **Modelo** (Java+Spring+PostgreSQL, Web Next.js, Python FastAPI). Pré-preenche descrição + oferece criar `CLAUDE.md` inicial.
3. **Nome**, **descrição**, **pastas** (drag-and-drop ou Adicionar pasta).
4. A **primeira pasta** vira o `cwd`; as demais entram como `--add-dir`.
5. Seção **Git/Worktree (override do projeto)** — opcional:
   - **Prefixo da branch**: substitui o `claude/` global (ex: `italo`).
   - **Isolar worktree por padrão**: `Usar global / Sim / Não`.
   - **Criar nova branch por padrão**: `Usar global / Sim / Não`.

## Abrindo o Claude

Ao clicar **Abrir Claude** num workspace, abre o `LaunchClaudeDialog`:

- **Pastas**: checkbox por pasta do workspace. Primeira marcada vira `cwd`, demais `--add-dir`.
- **Isolar em git worktree**: cria um worktree em `<repo-pai>/<repo>.claude/<branch>/`. Útil pra rodar múltiplos agentes em paralelo sem brigar de commit.
- **Criar nova branch**: 
  - Marcado + isolado → `git worktree add -b <branch> <path> <base>`
  - Marcado + sem isolar → `git checkout -b <branch> [<base>]` in-place
  - Desmarcado + isolado → checkout de branch existente num worktree
  - Desmarcado + sem isolar → roda na branch atual (nada muda)

Os defaults vêm de **Configurações → Worktree** ou do override do workspace (se setado).

## Sidebar: árvore de atividade

Cada workspace que tem console aberto vira expansível. Cada filho mostra:

```
⠋  Verificar falha ao inserir um novo status...
    Trabalhando
    Lendo arquivo MapBaseTest.java
```

Estados (cor + ícone):
- **Trabalhando** (amarelo + spinner ⠋⠙⠹…): Claude está pensando ou rodando tool
- **Aguardando** (laranja + !): Claude exibiu um permission prompt — precisa que você escolha algo
- **Ocioso** (azul-cinza + ❚❚): Claude terminou o turno e está no prompt principal sem nada pendente
- **Concluído** (verde + ✓): processo do Claude encerrado

**Double-click** num filho foca a aba do terminal correspondente. Sessões antigas (do histórico) aparecem como children também — double-click retoma via `--resume` no terminal embutido.

## Inbox global (bell 🔔) + notificações nativas

Quando algum console sai do estado **Trabalhando** (transição working → Ocioso ou Aguardando), ele entra no inbox global e o bell fica laranja com contador. Click no bell → menu com lista; click num item pula pro workspace + aba correspondente e remove do inbox.

Inbox também limpa quando: você foca o tab manualmente, o tab é fechado, ou clica em "Limpar inbox".

Em paralelo ao bell, o app:

- **Tray icon nativo** (`QSystemTrayIcon`) no painel do sistema. O menu repete a inbox (workspace + título da sessão); clique num item foca a aba.
- **Notificação D-Bus** com botões de ação (em ambientes que suportam — KDE, GNOME, Hyprland com mako/dunst):
  - **Abrir** → traz o app pra frente e foca a aba.
  - **Adiar** → some agora, volta a lembrar depois (re-lembretes a cada N minutos enquanto a sessão continuar idle).
  - **Já vi** → marca como vista e remove da inbox sem precisar abrir.
- **Snooze** também acessível pelo menu da tray.

Onde não tem D-Bus disponível, cai pro `notify-send` simples (sem botões). Toda essa parte é ativada via **Configurações → Notificações** (instala o hook `Stop` em `~/.claude/settings.json`).

## Catálogo (view top-level — 📚 / `Ctrl+Shift+2`)

Split horizontal: lista filtrável de Skills/Agents/Comandos à esquerda + painel de detalhe à direita.

- Filtros de tipo (Skills/Agents/Comandos), filtros de fonte (Projeto/Global/Plugin), busca por texto.
- Selecionar um item mostra: frontmatter, body completo, contagem de uso por workspace, **lint** (avisos sobre frontmatter mal formado), e botões pra editar / abrir no editor externo.
- **Playground**: testa o skill localmente passando args fictícios pra ver o que ele expandiria.

A versão "estreita" do mesmo catálogo continua no dock direito do workspace (lista + click copia `/nome`).

## Hooks (view top-level — 🪝 / `Ctrl+Shift+3`)

Inspector dos hooks do Claude Code. Mostra todos os hooks instalados em `~/.claude/settings.json` (e nos `settings.local.json` de cada projeto), agrupados por evento (`Stop`, `PreToolUse`, `PostToolUse`, etc), com legenda de cores por fonte.

## MCP servers (view top-level — 🔌 / `Ctrl+Shift+4`)

Lista de todos os MCP servers configurados em `~/.claude.json` (não só o postgres que o app gerencia). Selecionar um mostra: comando, args, env vars, scope. Útil pra diagnosticar `claude mcp list` sem sair do app.

Pra criar/editar o MCP postgres específico do workspace, continue usando os botões **Criar MCP / Editar MCP** no painel central — a view aqui é só leitura/inspeção.

## Plugins (view top-level — 🧩 / `Ctrl+Shift+5`)

Bundles que reagem a eventos do app e/ou expõem comandos pra paleta. Spec completa em `docs/PLUGIN_SPEC.md`.

- **Lista** de plugins instalados em `~/.config/claude-workspaces/plugins/<plugin>/`. Toggle enable/disable persiste em `<install>/.state/enabled.flag`.
- **Detalhe** do plugin selecionado: explicação amigável em PT-BR do que ele faz, manifest, permissões pedidas, último diretório de logs, configurações editáveis inline (auto-save).
- **Toolbar**:
  - **Exemplos**: instala bundles bundled do repo com um clique (`commit-coach`, `idle-rescue`, `focus-timer`, `workspace-snapshot`).
  - **Instalar de pasta**: aponta pra uma pasta com `plugin.yaml` válido.
  - **Solicitar criação**: abre dialog pra descrever um plugin novo; gera prompt e abre um Claude pra implementar.
  - **Recarregar**: rescaneia o diretório de plugins.
- **Paleta de comandos** (`Ctrl+P`): lista os comandos expostos pelos plugins ativos — invoca via teclado sem precisar abrir a view.

## Apps auxiliares (view top-level — 🧰 / `Ctrl+Shift+6`)

PWAs/sites embutidos via QtWebEngine — mantém ferramentas auxiliares (Taskis, ClickUp, Trello, Google Calendar, o que você quiser) dentro do app sem alt-tab.

- Lista lateral de apps configurados + webview à direita.
- Cada app tem **perfil isolado** em `~/.config/claude-workspaces/apps_profiles/<slug>/` — cookies/login persistem entre sessões e um app não enxerga cookie do outro.
- **Adicionar app**: dialog com nome + URL + ícone opcional. Persiste em `settings.json` (`apps` list).
- Vem com Taskis e ClickUp como defaults; você pode remover/substituir.

## Painel Git (dock direito)

Modelo IntelliJ Commit:

- **Tree de arquivos** agrupado em "Changes" (tracked modificado) e "Unversioned Files" (untracked). Checkbox por arquivo controla se entra no próximo commit.
- **Toolbar**: refresh, fetch, pull (ff-only), toggle do diff inline.
- **Click num arquivo** (com diff visível) mostra o diff colorido.
- **Double-click** abre o arquivo no editor configurado (VS Code por default).
- **Right-click** abre menu sensível ao estado:
  - Untracked → Add (stage), Deletar arquivo
  - Changes → Stage / Unstage / Rollback (git restore)
  - Grupos → Add todos / Unstage todos / Rollback todos
  - Repo → Pull / Fetch / Stage tudo / Abrir pasta
- **Área de commit** no rodapé: texto livre + botão `Commit (N)`. O commit reseta o staging, stage apenas os marcados, e roda `git commit -m`.

Auto-refresh via `QFileSystemWatcher` em `.git/index`, `.git/HEAD`, `.git/FETCH_HEAD` + poll de 30s.

### Abrir PR

Quando há commits ahead do remote, aparece o botão **Abrir PR** no painel Git. Ele usa o `gh` CLI:

1. Faz `git push -u` se a branch ainda não tem upstream.
2. Detecta se já existe PR aberto pra branch (`gh pr view`); se sim, oferece abrir no navegador em vez de criar duplicado.
3. Senão, abre o `OpenPRDialog` com título + corpo pré-preenchidos a partir do diff e dos commits da branch.
4. Cria o PR via `gh pr create` e copia a URL pra clipboard.

Pré-requisito: `gh` no PATH e autenticado (`gh auth status`). Sem `gh`, o botão fica oculto.

## Painel Memória (dock direito)

Editor inline do `CLAUDE.md` da **pasta primária** do workspace. Claude Code já carrega esse arquivo automaticamente quando inicia naquele `cwd` — o painel só dá UI ergonômica pra editar/salvar sem abrir IDE. Auto-save após 3s de inatividade.

## Painel Skills (dock direito)

Lista **Skills + Agents + Comandos** disponíveis:

- **Filtros de tipo**: Todos / Skills / Agentes / Comandos.
- **Filtros de fonte**: Todas / Projeto / Global (`~/.claude/skills/`) / Plugin (marketplaces).
- **Busca por texto** na descrição.
- Skills mostram **contagem de uso** lida dos JSONLs do Claude (ex: `/commit-arquivo · 47 uso(s) · 3d atrás`). Tooltip detalha breakdown por workspace.
- **Click copia** `/nome` na clipboard. Cola no Claude pra invocar.

## MCP postgres

Cada workspace pode ter um MCP `postgres` associado (linha "MCP:" no detalhes). 

- **Criar MCP** / **Editar MCP** abre dialog com URL postgres (`postgresql://user:senha@host:5432/db`).
- O nome do MCP é o nome do workspace (ex: workspace `ogpms` cria MCP chamado `ogpms`).
- App grava em `~/.claude.json` preservando o resto (cria backup `.bak-<ts>` antes, mantém 3).
- **Remover** desconfigura. Senha mascarada (`•••`) na exibição.

## Telemetria de uso/custo

Quando um workspace tem sessões nos últimos 30 dias, aparece uma linha:

```
Uso (30d): in 1.2M  ·  out 80K  ·  cache 5.4M  ·  ≈ US$ 12.34
```

Cost é estimado com preços hardcoded (atualizar `usage_telemetry.PRICING` quando Anthropic muda). Modelos desconhecidos contam tokens mas não custo.

## Busca em sessões (Ctrl+Shift+F)

Dialog dedicado pra busca de texto livre em **todas** as sessões antigas do Claude:

- Linha de busca debounced 300ms
- Combo de período (Tudo / Hoje / Semana / Mês / 3 meses) — default Semana
- Resultados mostram prompt original + timestamp + workspace + matches + **snippet com contexto** (±80 chars)
- Enter ou double-click retoma a sessão no terminal interno (acha automaticamente o workspace pelo cwd)

## Sessões recentes (cards)

No painel central. Mostra preview do 1º prompt, timestamp, badge da pasta de origem (multi-folder workspaces). Botões:

- **Remover**: apaga o `.jsonl` da sessão (irreversível).
- **→ Handoff**: abre dialog pra montar briefing e inicia novo Claude com esse briefing pré-enviado após 4s (e copia pra clipboard como backup).
- **Retomar**: abre nova aba do terminal com `claude --resume <id>`.

## Configurações

Acesse via `Ctrl+,` ou botão Configurar.

- **Comandos** (Claude, terminal, shell, IDEs): defaults `claude / konsole / (login shell) / code / idea / webstorm / pycharm / rider`. Override conforme sua instalação.
- **Args extras do Claude**: passados em todas as chamadas (ex: `--dangerously-skip-permissions`).
- **Worktree/Git defaults**:
  - Isolar worktree por padrão
  - Criar nova branch por padrão (quando isolar)
  - Prefixo da branch (ex: `italo` → branches sugeridas viram `italo/<timestamp>`)
- **Notificações**: instala/remove hook `Stop` no `~/.claude/settings.json` pra disparar `notify-send` ao fim de cada turno do Claude.
- **Abrir log**: abre `~/.local/state/claude-workspaces/app.log` no editor padrão.

Workspaces podem override os defaults de worktree/git individualmente (campo "Git/Worktree (override do projeto)" no `WorkspaceDialog`).

## Persistência de layout

Splitters, geometria da janela e estado dos painéis do dock (aberto/fechado) são salvos automaticamente após 600ms de inatividade. Arraste o handle, redimensione a janela, abra/feche painéis — tudo volta ao mesmo lugar na próxima sessão.

## Restaura abas Claude entre sessões do app

Ao fechar o app, ele salva em `~/.config/claude-workspaces/session_state.json` a lista de tabs Claude que estavam rodando (workspace + session_id + cwd) — só salva tabs cuja sessão JSONL já foi resolvida, pra garantir que o `--resume` no próximo startup vai casar com um arquivo real.

No próximo startup, recria cada aba via `claude --resume <session_id>` no mesmo workspace. Shells puros e tabs ainda não claimadas não são restauradas.

## Comandos úteis

```bash
# Ver últimos erros
tail -f ~/.local/state/claude-workspaces/app.log

# Resetar config (mantém workspaces)
rm ~/.config/claude-workspaces/settings.json

# Listar worktrees criados pelo app
ls ~/Projetos/**/*.claude/

# Forçar restauração de splitter ao default (sem mexer no resto)
python3 -c "
import json
p = '~/.config/claude-workspaces/settings.json'
import os; p = os.path.expanduser(p)
d = json.load(open(p))
d.pop('body_splitter_sizes', None)
d.pop('right_splitter_sizes', None)
json.dump(d, open(p, 'w'), indent=2)
"
```
