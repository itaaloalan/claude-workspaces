# Manual de desenvolvimento

## Setup

```bash
git clone https://github.com/itaaloalan/claude-workspaces.git
cd claude-workspaces

# Opção A — pacman (mais rápido em CachyOS/Arch)
sudo pacman -S pyside6
PYTHONPATH=src python3 -m claude_workspaces

# Opção B — venv
python -m venv .venv
source .venv/bin/activate  # ou .venv/bin/activate.fish
pip install -e .
claude-workspaces
```

## Estrutura

```
src/claude_workspaces/
├── app.py                 # entrypoint da QApplication
├── __main__.py            # permite `python -m claude_workspaces`
├── models.py              # dataclass Workspace
├── storage.py             # leitura/escrita de workspaces.json
├── settings.py            # dataclass Settings + persistência
├── stacks.py              # detecção de stack (Java/Web/Python/C#)
├── launchers.py           # spawn de Claude / terminal / IDEs
├── logging_setup.py       # config de logging + Qt handler + excepthook
└── ui/
    ├── main_window.py     # QMainWindow + QTabWidget + sidebar
    ├── workspace_details.py # painel direito da aba Workspaces
    ├── workspace_dialog.py  # diálogo criar/editar workspace
    └── settings_panel.py    # aba Configurações
```

```
packaging/
├── claude-workspaces.svg     # ícone (64x64 SVG)
├── install-launcher.sh       # instala .desktop e ícone em ~/.local/share
└── uninstall-launcher.sh
```

```
docs/
├── USAGE.md                  # manual do usuário
└── DEVELOPMENT.md            # este arquivo
```

## Arquitetura

A app é uma `QMainWindow` com `QTabWidget` no centro. Duas tabs:

1. **Workspaces** — `QSplitter` horizontal:
   - **Esquerda**: `QListWidget` de workspaces (clicar seleciona; `currentItemChanged` dispara o detalhe).
   - **Direita**: `WorkspaceDetailsPanel`, um `QStackedWidget` com dois estados (vazio / conteúdo do workspace selecionado).
2. **Configurações** — `SettingsPanel` (`QFormLayout` com `QLineEdit`s).

O estado mutável (lista de workspaces e `Settings`) vive em `MainWindow`. Painéis recebem a **mesma referência** de `Settings` para que mudanças propaguem sem signal mediator.

Workspaces e settings são persistidos em `~/.config/claude-workspaces/`. Logs em `~/.local/state/claude-workspaces/`.

## Como adicionar uma stack nova

Exemplo: detectar projetos **Rust** e oferecer botão "Abrir RustRover".

1. **`src/claude_workspaces/stacks.py`** — adicione o stack:
   ```python
   STACK_INDICATORS["rust"] = ["Cargo.toml"]
   STACK_LABEL["rust"] = "Rust"
   STACK_TO_IDE["rust"] = "rustrover"
   ```

2. **`src/claude_workspaces/settings.py`** — adicione o campo no `Settings`:
   ```python
   rustrover_command: str = "rustrover"
   ```
   E inclua em `ide_command()`:
   ```python
   "rustrover": self.rustrover_command,
   ```

3. **`src/claude_workspaces/launchers.py`** — atualize `IDE_LABEL`:
   ```python
   IDE_LABEL["rustrover"] = "RustRover"
   ```

4. **`src/claude_workspaces/ui/settings_panel.py`** — adicione um campo no formulário e na lógica de salvar / refresh.

Os botões dinâmicos no painel de detalhes são montados automaticamente a partir de `STACK_TO_IDE`, então só editar essas tabelas já adiciona o botão.

## Como customizar como o terminal é invocado

`launchers._run_in_terminal` chama:

```python
subprocess.Popen(
    [terminal_cmd, "-e", $SHELL, "-ic", "<comando>"],
    cwd=workspace.primary_folder,
)
```

A flag `-e` funciona em konsole, xterm, alacritty, foot. Para terminais que usam outra convenção (`kitty`, `gnome-terminal --`), edite essa função ou adicione um campo `terminal_exec_flag` em `Settings`.

O `-ic` no shell é o que permite resolução de aliases definidos em `.zshrc` / `config.fish` / `.bashrc`.

## Logging

Em qualquer módulo:

```python
import logging
log = logging.getLogger(__name__)

log.info("…")
log.warning("…")
log.exception("…")  # inclui traceback automaticamente
```

Configuração centralizada em `logging_setup.py`. Inclui:

- `RotatingFileHandler` em `~/.local/state/claude-workspaces/app.log`
- Handler no stderr
- `sys.excepthook` para exceções não tratadas
- `qInstallMessageHandler` para mensagens internas do Qt

Para subir o nível de log temporariamente:

```bash
PYTHONPATH=src python3 -c "
from claude_workspaces.logging_setup import setup_logging
import logging
setup_logging(logging.DEBUG)
from claude_workspaces.app import main
main()
"
```

## Convenções

- Type hints em tudo (`list[str]`, `Workspace | None`, etc. — exigem 3.11+).
- Dataclasses para modelos persistidos (`Workspace`, `Settings`); sempre com `to_dict`/`from_dict` para forward-compat do JSON.
- Erros nos launchers viram `LauncherError` que a UI captura e mostra em `QMessageBox.warning`.
- Strings de UI em PT-BR; identificadores e logs em EN/PT misto sem regra rígida.

## Roadmap interno

Próximos passos discutidos:

- **Terminal embutido** via `xterm.js + QWebEngineView + pty` (substitui "Abrir Claude" para rodar dentro da janela).
- Sinal de status por workspace (rodando / parado).
- Persistir tamanho do `QSplitter` e estado da sidebar entre execuções.
- Pacote AUR (`claude-workspaces-git`).

## Publicando alterações

```bash
git add <arquivos>
git commit -m "feat: ..."
git push
```

Repo: https://github.com/itaaloalan/claude-workspaces
