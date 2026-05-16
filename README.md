# claude-workspaces

Gerenciador de workspaces e console multi-sessão pra Claude Code, com terminal embutido, dock de ferramentas e visibilidade do que cada agente está fazendo.

![status](https://img.shields.io/badge/status-active-success) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![tests](https://img.shields.io/badge/tests-130-green)

## O problema

O Claude Code é poderoso mas trabalhar em vários projetos ao mesmo tempo vira bagunça: várias janelas abertas, contexto misturado, difícil saber qual console está esperando você, qual está trabalhando, custo descontrolado, sessões antigas perdidas, branches colidindo.

## O que o app entrega

- **Workspaces**: cada projeto tem um nome, lista de pastas e configurações próprias. Abrir o Claude num workspace passa essas pastas como contexto isolado.
- **Terminal embutido** (xterm.js + pty): múltiplas abas de Claude por workspace, sem janelas externas.
- **Inbox global**: bell badge no topbar aviso quando algum console termina e está esperando você (✓ "Aguardando").
- **Sidebar com árvore de atividade**: cada console rodando aparece sob seu workspace com estado em tempo real (Trabalhando · spinner / Aguardando ❚❚ / Concluído ✓) e o título da sessão.
- **Worktrees opcionais**: ao abrir Claude, escolha se quer isolar em git worktree numa nova branch (ou existente) — útil pra rodar múltiplos agentes no mesmo repo em paralelo.
- **Painel Git estilo IntelliJ**: árvore de arquivos com checkboxes pra seletivamente staged + commit inline. Right-click pra Add/Unstage/Rollback/Delete.
- **Telemetria de tokens/custo** por workspace (lê os JSONLs do Claude).
- **Skills/Agents/Comandos** listados com filtros, contadores de uso (% e quando), clique copia `/nome`.
- **Memória do workspace**: editor inline do CLAUDE.md da pasta primária.
- **Busca em sessões** (Ctrl+Shift+F): texto livre em todas as sessões antigas com snippet.
- **Handoff**: botão "→ Tarefa" passa contexto de uma sessão pra outra com briefing pré-preenchido.
- **MCP postgres**: cria/edita config do MCP postgres do Claude por workspace.
- **Templates**: 4 bundled (Vazio, Java+Spring+PostgreSQL, Web Next.js, Python FastAPI) ou JSONs custom em `~/.config/claude-workspaces/templates/`.

## Instalação

### Arch / CachyOS via AUR

```bash
paru -S claude-workspaces  # ou yay -S claude-workspaces
```

### Manual (qualquer distro)

Requisitos:
- Python 3.11+
- PySide6 (`pip install PySide6` ou pacote do sistema)
- CLI do [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` no PATH)
- Git (pro painel Git e worktrees)
- Konsole ou outro terminal (fallback pra alguns botões de launcher)

```bash
git clone https://github.com/itaaloalan/claude-workspaces.git ~/Projetos/claude-workspaces
cd ~/Projetos/claude-workspaces
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/claude-workspaces
```

Pra instalar o `.desktop` no menu do KDE/GNOME:

```bash
./packaging/install-launcher.sh
```

## Atalhos principais

| Atalho | Função |
|---|---|
| `Ctrl+N` | Novo workspace |
| `Ctrl+1` … `Ctrl+9` | Pular pro N-ésimo workspace |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Próximo / anterior workspace |
| `Ctrl+F` | Focar busca (filtro do topbar) |
| `Ctrl+Shift+F` | Buscar texto em todas as sessões antigas |
| `Ctrl+Enter` | Abrir Claude no workspace atual |
| `Ctrl+B` / `Ctrl+J` / `Ctrl+Shift+B` | Toggle sidebar / terminal / dock direito |
| `Ctrl+T` / `Ctrl+Shift+W` / `Ctrl+K` | Nova aba shell / fechar aba / limpar terminal |
| `Ctrl+P` | Quick open de arquivo do workspace |
| `Ctrl+O` | Abrir pasta primária no gerenciador de arquivos |
| `Ctrl+Shift+C` | Copiar caminho da pasta primária |
| `Ctrl+,` | Configurações |
| `Ctrl+/` ou `F1` | Diálogo com todos os atalhos |

## Onde os dados ficam

| O quê | Caminho |
|---|---|
| Workspaces | `~/.config/claude-workspaces/workspaces.json` |
| Configurações | `~/.config/claude-workspaces/settings.json` |
| Templates custom | `~/.config/claude-workspaces/templates/*.json` |
| Backups do MCP | `~/.claude.json.bak-<timestamp>` (3 mais recentes) |
| Logs | `~/.local/state/claude-workspaces/app.log` |
| Worktrees criados | `<repo-pai>/<repo>.claude/<branch>/` |

## Documentação

- [docs/USAGE.md](docs/USAGE.md) — manual do usuário
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — arquitetura, como estender, layout dos módulos
- [docs/MAINTAINABILITY.md](docs/MAINTAINABILITY.md) — relatório de auditoria + tracking de débito técnico

## Status

Funcional e em uso diário. 130 testes, CI rodando lint + pytest. Próximas direções: persistir aba de terminal entre execuções, integração com mais MCPs além do postgres, atalho global pra pular pro app via systemd unit.
