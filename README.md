# claude-workspaces

Gerenciador de workspaces para Linux/KDE focado em rodar o Claude Code com contexto isolado por projeto.

## O que é

Cada workspace tem um nome e uma lista de pastas. Ao lançar o `claude` a partir de um workspace, ele é aberto no Konsole com a primeira pasta como cwd e as demais via `--add-dir` — assim cada projeto tem seu próprio contexto, sem misturar com os outros.

Resolve o problema de ter uma única janela de editor enxergando todos os projetos ao mesmo tempo e bagunçando o contexto do agente.

## Status

Em desenvolvimento — esqueleto inicial.

## Requisitos

- Python 3.11+
- PySide6 (`sudo pacman -S pyside6` no Arch/CachyOS, ou `pip install PySide6`)
- KDE Konsole
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` no PATH)

## Rodar em modo dev

```bash
git clone https://github.com/<user>/claude-workspaces.git
cd claude-workspaces
python -m venv .venv
source .venv/bin/activate.fish  # ou .venv/bin/activate no bash/zsh
pip install -e .
claude-workspaces
```

Sem instalar:

```bash
PYTHONPATH=src python -m claude_workspaces
```

## Onde os workspaces ficam salvos

`~/.config/claude-workspaces/workspaces.json`
