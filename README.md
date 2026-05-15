# claude-workspaces

Gerenciador de workspaces para Linux/KDE focado em rodar o Claude Code com contexto isolado por projeto.

## O que é

Cada workspace tem um nome e uma lista de pastas. Ao lançar o `claude` a partir de um workspace, ele é aberto no Konsole com a primeira pasta como cwd e as demais via `--add-dir` — assim cada projeto tem seu próprio contexto, sem misturar com os outros.

Resolve o problema de ter uma única janela de editor enxergando todos os projetos ao mesmo tempo e bagunçando o contexto do agente.

## Features

- Sidebar com lista de workspaces + painel de detalhes à direita
- Aba **Configurações** com comando do Claude / terminal / IDEs customizáveis
- Suporte a alias de shell (`ia` → `claude` via `$SHELL -ic`)
- **Auto-detecção de stack** (Java, Web, Python, C#) por arquivos do projeto
- Botões dinâmicos: IntelliJ, WebStorm, PyCharm, Rider, VS Code
- Botão **🔧 Hack este app** abre o Claude no próprio repo do `claude-workspaces`
- Logging em `~/.local/state/claude-workspaces/app.log`

## Instalação rápida (Arch / CachyOS / KDE)

```bash
sudo pacman -S pyside6 konsole
git clone https://github.com/itaaloalan/claude-workspaces.git ~/Projetos/claude-workspaces
cd ~/Projetos/claude-workspaces
./packaging/install-launcher.sh
```

Procure por **Claude Workspaces** no menu iniciar do KDE.

Para desinstalar: `./packaging/uninstall-launcher.sh`.

## Documentação

- [docs/USAGE.md](docs/USAGE.md) — manual do usuário (criação de workspace, configuração, atalhos)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — arquitetura, como adicionar stack/IDE, logging, etc.

## Status

Em desenvolvimento ativo. Próximo passo: terminal embutido na janela (xterm.js + pty).

## Onde os arquivos ficam

| O quê | Caminho |
|---|---|
| Workspaces | `~/.config/claude-workspaces/workspaces.json` |
| Configurações | `~/.config/claude-workspaces/settings.json` |
| Logs | `~/.local/state/claude-workspaces/app.log` |
