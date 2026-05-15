# Manual de uso

## Instalação rápida (Arch / CachyOS / KDE)

```bash
# 1. Dependências de sistema
sudo pacman -S pyside6 konsole

# 2. Clone e instale o launcher no menu do KDE
git clone https://github.com/itaaloalan/claude-workspaces.git ~/Projetos/claude-workspaces
cd ~/Projetos/claude-workspaces
./packaging/install-launcher.sh
```

Procure por **Claude Workspaces** no menu iniciar do KDE.

### Outras distros

Você precisa de:

- Python 3.11+
- PySide6 (`pip install PySide6` ou pacote do sistema)
- Um terminal compatível com a flag `-e` (Konsole, xterm, alacritty, foot)
- O CLI do [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` no PATH)

Rodar direto do source:

```bash
PYTHONPATH=src python3 -m claude_workspaces
```

Ou instalar como pacote:

```bash
pipx install --editable .
```

## Criando um workspace

1. Clique em **+ Novo** na barra lateral
2. Dê um **nome** (ex: "API Petrobras")
3. Adicione uma **descrição** (opcional)
4. Use **Adicionar pasta** uma ou mais vezes — a **primeira pasta** é o `cwd` que o Claude vai usar; as demais entram via `--add-dir`
5. Use **Mover ↑ / ↓** para reordenar se quiser
6. **OK** salva

O JSON fica em `~/.config/claude-workspaces/workspaces.json` — pode versionar, sincronizar ou editar manualmente.

## Botões de "Abrir com"

Quando um workspace é selecionado, a área da direita mostra os botões disponíveis:

| Botão | O que faz |
|---|---|
| **Abrir Claude** | Abre o terminal configurado rodando `claude --add-dir ...` no `cwd` do workspace |
| **Abrir Terminal** | Abre só o terminal (Konsole por padrão) no `cwd` |
| **Abrir IntelliJ IDEA / WebStorm / PyCharm / Rider** | Aparecem dinamicamente quando a stack é detectada nos arquivos do projeto |
| **Abrir VS Code** | Sempre presente, passa todas as pastas do workspace como args |

### Auto-detecção de stack

| Stack | Arquivos detectados | IDE sugerida |
|---|---|---|
| Java | `pom.xml`, `build.gradle(.kts)`, `settings.gradle(.kts)` | IntelliJ IDEA |
| Web | `package.json`, `yarn.lock`, `pnpm-lock.yaml` | WebStorm |
| Python | `pyproject.toml`, `setup.py`, `requirements.txt`, `Pipfile` | PyCharm |
| C# | `*.csproj`, `*.sln`, `*.fsproj` | Rider |

Workspaces poliglotas mostram **todos** os botões aplicáveis.

## Aba Configurações

Customize os comandos usados pelos botões:

- **Comando do Claude** — default `claude`. Se você tem alias `ia` no fish/zsh, coloque `ia` aqui (o app roda via `$SHELL -ic` então aliases são resolvidos).
- **Args extras do Claude** — passados em todas as chamadas (ex: `--dangerously-skip-permissions`).
- **Terminal** — default `konsole`. Pode ser `alacritty`, `kitty`, `foot`, etc.; o app passa `-e <shell>` para executar.
- **Comandos das IDEs** — default `idea`, `webstorm`, `pycharm`, `rider`, `code`. Ajuste se sua instalação usar outro nome (ex: `code-insiders`, `intellij-idea-ultimate`).

Configurações são salvas em `~/.config/claude-workspaces/settings.json`.

## Barra lateral

- Clique em **☰** ou arraste a borda do divisor para esconder/mostrar a sidebar.
- O **🔧 Hack este app** (pé da sidebar) abre o Claude no próprio repositório do `claude-workspaces` para você iterar usando o próprio app.

## Logs

Logs ficam em `~/.local/state/claude-workspaces/app.log` (rotação automática em ~2MB, 3 backups).

A aba **Configurações** tem um botão **Abrir log** que abre o arquivo no editor padrão.

## Atalhos úteis

```bash
# Ver últimos erros
tail -f ~/.local/state/claude-workspaces/app.log

# Limpar workspaces (cuidado, sem confirmação)
rm ~/.config/claude-workspaces/workspaces.json

# Resetar configurações
rm ~/.config/claude-workspaces/settings.json
```
