# claude-workspaces

Gerenciador de workspaces e console multi-sessão pra Claude Code, com terminal embutido, dock de ferramentas e visibilidade do que cada agente está fazendo.

![status](https://img.shields.io/badge/status-active-success) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![tests](https://img.shields.io/badge/tests-443-green)

## O problema

O Claude Code é poderoso mas trabalhar em vários projetos ao mesmo tempo vira bagunça: várias janelas abertas, contexto misturado, difícil saber qual console está esperando você, qual está trabalhando, custo descontrolado, sessões antigas perdidas, branches colidindo.

## O que o app entrega

- **Workspaces**: cada projeto tem um nome, lista de pastas e configurações próprias. Abrir o Claude num workspace passa essas pastas como contexto isolado.
- **Terminal embutido** (xterm.js + pty): múltiplas abas de Claude por workspace, sem janelas externas.
- **Activity bar**: coluna vertical à esquerda com views top-level — Workspaces, Catálogo (skills/agents/commands), Hooks, MCP servers, Plugins, Apps. Atalhos `Ctrl+Shift+1..6`.
- **Inbox global + notificações nativas**: bell no topbar (transição working → não-working), `QSystemTrayIcon` no painel do sistema com menu da inbox e re-lembretes a cada N minutos. Em sessões com D-Bus, a notificação ganha botões **Abrir / Adiar / Já vi**.
- **Sidebar com árvore de atividade**: cada console rodando aparece sob seu workspace com estado em tempo real (Trabalhando · spinner / Aguardando ! / Ocioso ❚❚ / Concluído ✓) e o título da sessão. "Aguardando" só aparece quando Claude exibe um permission prompt — turnos terminados sem ação pendente ficam como "Ocioso".
- **Restaura abas Claude**: ao fechar o app, salva as sessões Claude em curso e reabre tudo com `--resume` no próximo startup.
- **Worktrees opcionais**: ao abrir Claude, escolha se quer isolar em git worktree numa nova branch (ou existente) — útil pra rodar múltiplos agentes no mesmo repo em paralelo.
- **Painel Git estilo IntelliJ**: árvore de arquivos com checkboxes pra seletivamente staged + commit inline. Right-click pra Add/Unstage/Rollback/Delete.
- **Abrir PR direto da UI**: depois de um commit, botão pra `gh pr create` com título/corpo gerados a partir do diff e dos commits da branch.
- **Telemetria de tokens/custo** por workspace (lê os JSONLs do Claude).
- **Skills/Agents/Comandos** listados com filtros, contadores de uso (% e quando), clique copia `/nome`. Editor + lint + playground integrados no Catálogo.
- **Plugins** (manifest v2): bundles que podem reagir a eventos do app (`tab_idle`, `tab_started`, etc), expor comandos pra paleta e configurações editáveis inline. Botão "Exemplos" instala bundles do repo com um clique; botão "Solicitar criação" pede pro Claude desenhar um plugin novo. Detalhe em [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md).
- **Apps auxiliares**: PWAs/sites embutidos via QtWebEngine (Taskis, ClickUp, ou o que você adicionar) com perfil isolado por app — login persiste e um app não enxerga cookie do outro.
- **Memória do workspace**: editor inline do CLAUDE.md da pasta primária.
- **Busca em sessões** (Ctrl+Shift+F): texto livre em todas as sessões antigas com snippet.
- **Handoff**: botão "→ Tarefa" passa contexto de uma sessão pra outra com briefing pré-preenchido (inclui branch, ahead/behind, arquivos modificados).
- **MCP postgres**: cria/edita config do MCP postgres do Claude por workspace. View "MCP servers" mostra tudo que está configurado em `~/.claude.json`.
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

Pra rodar em background no login + atalho global de "trazer pra frente":

```bash
./packaging/install-systemd.sh
```

Esse script cria uma systemd user unit (`claude-workspaces.service`) e um
helper `~/.local/bin/claude-workspaces-focus`. Vincule esse helper a um
atalho global no seu DE (KDE/GNOME/Hyprland) e o app vem pra frente em
qualquer lugar.

## Atalhos principais

| Atalho | Função |
|---|---|
| `Ctrl+N` | Novo workspace |
| `Ctrl+1` … `Ctrl+9` | Pular pro N-ésimo workspace |
| `Ctrl+Shift+1` … `Ctrl+Shift+6` | Trocar de view (Workspaces / Catálogo / Hooks / MCP / Plugins / Apps) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Próximo / anterior workspace |
| `Ctrl+F` | Focar busca (filtro do topbar) |
| `Ctrl+Shift+F` | Buscar texto em todas as sessões antigas |
| `Ctrl+Shift+R` | Retomar última sessão do workspace atual |
| `Ctrl+Enter` | Abrir Claude no workspace atual |
| `Ctrl+B` / `Ctrl+J` / `Ctrl+Shift+B` | Toggle sidebar / terminal / dock direito |
| `Ctrl+T` / `Ctrl+Shift+W` / `Ctrl+K` | Nova aba shell / fechar aba / limpar terminal |
| `Ctrl+Alt+←` / `Ctrl+Alt+→` | Aba anterior / próxima do terminal |
| `Ctrl+P` | Paleta de comandos de plugins |
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
| Estado das sessões Claude ativas | `~/.config/claude-workspaces/session_state.json` |
| Plugins instalados | `~/.config/claude-workspaces/plugins/<plugin>/` |
| Perfis isolados dos Apps | `~/.config/claude-workspaces/apps_profiles/<slug>/` |
| Backups do MCP | `~/.claude.json.bak-<timestamp>` (3 mais recentes) |
| Logs | `~/.local/state/claude-workspaces/app.log` |
| Worktrees criados | `<repo-pai>/<repo>.claude/<branch>/` |

## Documentação

- [docs/USAGE.md](docs/USAGE.md) — manual do usuário
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — arquitetura, como estender, layout dos módulos
- [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md) — spec dos plugins (manifest v2, eventos, permissões)
- [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) — plano de build/distribuição (Linux, macOS, Windows)
- [docs/MAINTAINABILITY.md](docs/MAINTAINABILITY.md) — relatório de auditoria + tracking de débito técnico

## Status

Funcional e em uso diário. 443 testes, CI rodando lint + pytest + mypy (não-bloqueante) + coverage. Veja [docs/MAINTAINABILITY.md](docs/MAINTAINABILITY.md) pro tracking de débito técnico — todos os itens da auditoria 2026-05-15 foram resolvidos.
