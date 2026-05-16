# Manual de uso

Visão geral do que cada parte da janela faz e como usar.

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│ ☰  Claude Workspaces  [busca…]                🔔  ⚙ Configurar│  ← topbar
├──────────┬──────────────────────────────────────────┬────────┤
│ WORK-    │  Workspace selecionado                    │ Git   │
│ SPACES   │  ─ título, stack, pastas, MCP, uso (30d)  │ ····  │
│          │  ─ ações (Abrir Claude / Terminal / IDEs) │       │
│ ▼ ogpms  │  ─ Sessões recentes (cards)               │       │
│  ⠋ Cons1 │                                            │ Mem.  │
│  ❚❚ Cons2│                                            │       │
│ ▼ map    │                                            │ Skills│
│          ├──────────────────────────────────────────┬┤       │
│          │ Terminal embutido (várias abas)          ││       │
│          │  ─ ⬇ ▢ ❐  (minimizar/maximizar/restaurar)││       │
└──────────┴──────────────────────────────────────────┴────────┘
```

- **Topbar**: toggle sidebar (☰), título, busca de workspaces, **bell** (consoles aguardando), Configurar.
- **Sidebar**: lista de workspaces. Cada workspace pode expandir e mostrar os consoles ativos como filhos com status colorido.
- **Centro/topo**: detalhes do workspace selecionado.
- **Centro/baixo**: terminal embutido (xterm.js + pty), com tabs por sessão.
- **Dock direito**: Git, Memória (CLAUDE.md), Skills — colapsáveis via tool strip vertical.

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
- **Aguardando** (laranja + ❚❚): Claude terminou turno, espera input
- **Concluído** (verde + ✓): processo do Claude encerrado

**Double-click** num filho foca a aba do terminal correspondente. Sessões antigas (do histórico) aparecem como children também — double-click retoma via `--resume` no terminal embutido.

## Inbox global (bell 🔔)

Quando algum console transiciona de **Trabalhando → Aguardando**, ele entra no inbox global e o bell ficar laranja com contador. Click no bell → menu com lista; click num item pula pro workspace + aba correspondente e remove do inbox.

Inbox também limpa quando: você foca o tab manualmente, o tab é fechado, ou clica em "Limpar inbox".

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
