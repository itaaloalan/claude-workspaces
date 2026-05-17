# Plano de build e distribuição multi-plataforma

Este documento descreve como empacotar e distribuir o `claude-workspaces` para
**Linux (várias distros)**, **macOS** e **Windows**, a partir do estado atual
do projeto.

> Hoje o projeto roda **somente em Linux** (KDE-friendly). Tem PKGBUILD pro AUR,
> um `install-launcher.sh` que cria o `.desktop`, e dependências GUI via
> PySide6. O resto é Python 3.11+ puro. Os pontos abaixo descrevem o que falta
> pra cada destino e qual é o caminho recomendado.

---

## 1. Diagnóstico do que prende o app no Linux hoje

Antes de qualquer build cross-platform, três pontos precisam ser endereçados —
todos relativamente isolados:

| Arquivo                              | Dependência Linux-only                | O que fazer                                                                  |
|--------------------------------------|---------------------------------------|------------------------------------------------------------------------------|
| `pty_session.py`                     | `pty`, `fcntl`, `termios`, `os.fork`  | Abstrair atrás de `PtyBackend` (POSIX → atual; Windows → `pywinpty`/ConPTY)  |
| `launchers.py` (`effective_shell`)   | `pwd.getpwuid`, `/etc/passwd`         | `if sys.platform == "win32"` retorna `cmd.exe`/`pwsh`; macOS usa `$SHELL`    |
| `settings.py` (`terminal_command`)   | default `"konsole"`                   | Default por plataforma: Konsole (Linux KDE), Terminal.app (mac), wt (Win)    |
| `packaging/notify-hook.py`           | `notify-send` (libnotify)             | macOS → `osascript`; Windows → `win10toast` ou `WinRT.Toast`                 |
| `hook_manager.py` (Stop hook)        | path `~/.claude/settings.json`        | OK em todas as plataformas — `Path.home()` já é portável                     |

Outros pontos que **já são portáveis** e não precisam mexer: storage JSON,
git via subprocess, telemetria de tokens, descoberta de skills, parsing das
sessions do Claude.

Recomendação: **criar `src/claude_workspaces/platform/`** com submódulos
`pty_backend.py`, `terminal_default.py`, `notify.py`. Mantém o resto do código
agnóstico.

---

## 2. Linux — distribuir além do AUR

### 2.1 O que já existe
- `packaging/aur/PKGBUILD` + `.install` + `.desktop` (Arch/CachyOS).
- `packaging/install-launcher.sh` (qualquer distro, instala `.desktop` no
  `~/.local/share/applications`).
- Wheel via `python -m build` (qualquer distro com Python 3.11+).

### 2.2 Caminhos novos recomendados

**A) Flatpak (cobre Fedora, Ubuntu, openSUSE, Debian, etc. de uma vez)**

- Criar `packaging/flatpak/io.github.itaaloalan.ClaudeWorkspaces.yaml`.
- Runtime: `org.kde.Platform//6.7` (já traz PySide6/Qt6, evita compilar Qt).
- Módulos: `python3-PyYAML` e o próprio wheel via `pip install`.
- Permissões mínimas:
  ```yaml
  finish-args:
    - --share=ipc
    - --share=network
    - --socket=wayland
    - --socket=fallback-x11
    - --device=dri
    - --filesystem=home          # precisa pra abrir worktrees em qualquer pasta
    - --filesystem=xdg-config/claude:rw   # ~/.claude
    - --talk-name=org.freedesktop.Notifications
  ```
- Publicar no **Flathub** depois de estabilizar — abre PR em
  `flathub/flathub` com o manifesto.
- ⚠️ Atenção: dentro do sandbox Flatpak o `subprocess` que chama `git`,
  `konsole`, `code` precisa rodar via `flatpak-spawn --host`. Adicionar wrapper
  em `launchers.py`:
  ```python
  if os.environ.get("FLATPAK_ID"):
      argv = ["flatpak-spawn", "--host", *argv]
  ```

**B) Debian/Ubuntu via `.deb`**

- Usar `stdeb` ou `dh-python` em `packaging/debian/`.
- `debian/control` declara `python3-pyside6.qtcore`, `python3-yaml`,
  `python3 (>= 3.11)`.
- Build com `dpkg-buildpackage -us -uc`.
- Publicar num PPA (Launchpad) ou hospedar `.deb` direto nas releases do GitHub.

**C) Fedora `.rpm`**

- Spec file em `packaging/rpm/claude-workspaces.spec`.
- Build em container Fedora: `rpmbuild -ba`.
- COPR pra publicar (`copr-cli build claude-workspaces ...`).

**D) AppImage (one-binary universal)**

- `pyside6-deploy` ou `python-appimage` geram AppImage com Python+Qt embutidos.
- Vantagem: roda em qualquer glibc moderna sem instalar nada.
- Hospedar na release do GitHub.

**Prioridade sugerida:**
1. **Flatpak** (cobre maior fatia do mercado com um único build).
2. **AppImage** (fallback "baixe e execute" pra qualquer distro).
3. `.deb`/`.rpm` só se houver demanda — Flatpak+AppImage já cobre.
4. Manter AUR (já temos).

---

## 3. macOS

### 3.1 O que precisa antes do build
- Endereçar `pty_session.py` — POSIX puro funciona no mac, só precisa não
  importar `fcntl`/`termios` de forma incompatível. Validar.
- Default `terminal_command` → `"Terminal"` (Terminal.app) ou `"iterm"`.
- Notificação: `osascript -e 'display notification "..." with title "..."'`.
- O `subprocess` que chama `git`, `gh`, `code` funciona igual.

### 3.2 Build do `.app`

Ferramentas-padrão:
- **py2app** (clássico, bem suportado pra PySide6)
- **briefcase** (BeeWare, mais moderno; também faz Windows e Linux)
- **pyside6-deploy** (oficial da Qt; usa Nuitka por baixo)

Recomendação: **`pyside6-deploy`** — é o caminho oficial, gera
`Claude Workspaces.app` com Python+Qt embutidos.

```
pip install "pyside6-deploy"
pyside6-deploy src/claude_workspaces/__main__.py \
    --name "Claude Workspaces" \
    --icon packaging/macos/claude-workspaces.icns
```

Output: `dist/Claude Workspaces.app`.

### 3.3 Distribuição

- **Assinatura (codesign):** precisa de Developer ID Application certificate
  ($99/ano Apple Developer Program). Sem isso o Gatekeeper bloqueia, usuário
  precisa fazer Ctrl+click → Open na primeira vez. Documentar isso no README.
- **Notarização:** `xcrun notarytool submit`. Sem notarização, mesmo assinado
  mostra warning.
- **DMG:** empacotar o `.app` num `.dmg` com `create-dmg`:
  ```
  brew install create-dmg
  create-dmg --volname "Claude Workspaces" \
             --window-size 600 400 \
             dist/Claude-Workspaces.dmg dist/
  ```
- **Homebrew Cask** (caminho "instalar via CLI"): criar formula em
  `homebrew-claude-workspaces/Casks/claude-workspaces.rb` apontando pra DMG do
  GitHub release. Documentar `brew tap itaaloalan/claude-workspaces`.

**Arquiteturas:** PySide6 tem wheel pra `arm64` (Apple Silicon) e `x86_64`.
Build em runner ARM (GitHub macos-14) cobre 95% dos macs modernos; build
universal (`--arch universal2`) só se houver demanda real.

---

## 4. Windows

### 4.1 O que precisa antes do build (maior esforço dos três)

- **PTY:** o backend atual (`pty`/`fcntl`) **não existe no Windows**. Trocar
  por `pywinpty` (binding ConPTY). API parecida — `winpty.PtyProcess.spawn()`,
  read/write/resize. Refatorar `pty_session.py` atrás de uma interface.
- **Shell padrão:** `cmd.exe` ou `pwsh.exe`. `effective_shell()` precisa olhar
  `%COMSPEC%`.
- **Terminal padrão:** `wt.exe` (Windows Terminal) se disponível, senão
  `cmd.exe`. `wt -d <cwd> -- pwsh -NoExit -Command "..."`.
- **Notificação:** `winrt.windows.ui.notifications` (Win10+) ou biblioteca
  `winotify`.
- **Paths em `git_actions.py`/`hook_manager.py`:** já usam `pathlib`, então
  ok. Validar que não há `os.path.join` com `/` hardcoded em outro lugar.
- **Linha de comando do Claude CLI:** validar se o próprio `claude` CLI tem
  build pra Windows; se não, deixar documentado que rodar via WSL é uma opção.

### 4.2 Build do `.exe`/instalador

Opções:
- **PyInstaller** (mais maduro, gera `.exe` autônomo com Python+Qt embutidos).
- **pyside6-deploy** (oficial, usa Nuitka — também gera `.exe`).
- **briefcase** (gera MSI direto).

Recomendação: **PyInstaller** + **Inno Setup** (instalador `.exe`).

```
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "ClaudeWorkspaces" \
    --icon packaging/windows/claude-workspaces.ico \
    --add-data "src/claude_workspaces/ui/static;claude_workspaces/ui/static" \
    src/claude_workspaces/__main__.py
```

Depois, Inno Setup script (`packaging/windows/installer.iss`) gera o
`ClaudeWorkspaces-Setup.exe` com atalhos no menu Iniciar e desinstalador.

### 4.3 Distribuição

- **Assinatura de código:** comprar certificado EV Code Signing (~$300/ano)
  pra evitar SmartScreen warning. Sem isso, primeira execução mostra "Windows
  protegeu seu PC". Documentar no README.
- **winget:** depois de estabilizar, abrir PR em
  `microsoft/winget-pkgs` com manifest YAML apontando pro `.exe` do release.
  Permite `winget install claude-workspaces`.
- **Chocolatey** (opcional): empacote `.nupkg` e publica em chocolatey.org.
- **Scoop** (opcional, comunidade dev): bucket próprio em
  `itaaloalan/scoop-claude-workspaces`.

---

## 5. CI/CD — onde construir cada artefato

Adicionar workflows em `.github/workflows/`:

| Workflow                  | Runner            | Artefato                         |
|---------------------------|-------------------|----------------------------------|
| `build-wheel.yml`         | `ubuntu-latest`   | `claude_workspaces-*.whl` (PyPI) |
| `build-linux-appimage.yml`| `ubuntu-22.04`    | `ClaudeWorkspaces-x86_64.AppImage` |
| `build-flatpak.yml`       | `ubuntu-latest` + `flatpak-builder` | `.flatpak` bundle      |
| `build-macos.yml`         | `macos-14` (ARM)  | `Claude-Workspaces.dmg`          |
| `build-windows.yml`       | `windows-latest`  | `ClaudeWorkspaces-Setup.exe`     |
| `release.yml`             | qualquer          | Anexa tudo numa GitHub Release   |

Trigger: `on: push: tags: ['v*']`. Tag `v0.2.0` → todos os builds rodam em
paralelo → release única no GitHub com 5 artefatos + publicação no PyPI
(`twine upload`).

---

## 6. PyPI — caminho mais simples e ortogonal

Independente das builds nativas, vale publicar o wheel no PyPI:

```
python -m build
twine upload dist/*
```

Aí qualquer um em qualquer plataforma faz `pipx install claude-workspaces`.
Bom pra usuários técnicos. Não substitui o `.dmg`/`.exe` (que dá ícone, menu,
zero-config), mas é o caminho de menor fricção pra desenvolvedores.

---

## 7. Ordem de execução sugerida

Roadmap incremental, em ordem de ROI:

1. **Refatorar plataforma-específicos** (`platform/` package, sem mudar
   comportamento no Linux).
2. **PyPI** — publica `0.2.0`. Esforço: 1 hora.
3. **Flatpak** — submete pro Flathub. Esforço: 1-2 dias (manifest + testes).
4. **AppImage** — pyside6-deploy + upload na release. Esforço: meio dia.
5. **macOS DMG** (sem assinatura, com instrução de "Ctrl+click → Open").
   Esforço: 1 dia. Adicionar assinatura/notarização quando virar prioridade.
6. **Windows .exe** — o mais caro porque precisa do `pywinpty` swap. Esforço:
   3-5 dias incluindo testes.
7. **winget/Homebrew** — só depois que as builds estiverem estáveis.

---

## 8. Riscos e pontos de atenção

- **PySide6 é pesado:** ~150-300 MB por instalador nativo. AppImage e
  PyInstaller bundles ficam grandes. Documentar isso.
- **Claude CLI dependência externa:** o app não embute o `claude` CLI. Em
  todas as plataformas, usuário precisa instalar Claude Code separadamente.
  Adicionar checagem `shutil.which("claude")` no startup com mensagem
  amigável.
- **`git`, `gh` dependências externas:** mesma coisa. No mac e Windows os
  instaladores precisam mencionar isso no README/welcome screen.
- **xterm.js (`QWebEngineView`):** já vem com PySide6, sem custo extra.
- **Assinatura de código** (mac+Win) é o maior bloqueador "não-técnico" —
  custa dinheiro e tem burocracia. Plano realista: lançar sem assinatura
  primeiro, documentar o workaround, comprar certificados depois que houver
  base de usuários.
