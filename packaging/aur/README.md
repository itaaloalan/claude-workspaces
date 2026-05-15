# AUR — claude-workspaces

Scripts pra empacotar o `claude-workspaces` no AUR.

## Publicar uma nova versão

1. Bater a versão em `pyproject.toml` e em `PKGBUILD` (`pkgver=`).
2. Criar a tag e push:
   ```
   git tag v0.1.0
   git push --tags
   ```
3. Atualizar `sha256sums` no PKGBUILD pegando o hash do tarball:
   ```
   curl -sL https://github.com/itaaloalan/claude-workspaces/archive/refs/tags/v0.1.0.tar.gz | sha256sum
   ```
4. Testar o build localmente:
   ```
   cd packaging/aur
   makepkg -sf
   ```
5. Publicar no AUR (depois de clonar `ssh://aur@aur.archlinux.org/claude-workspaces.git`):
   ```
   makepkg --printsrcinfo > .SRCINFO
   git add PKGBUILD .SRCINFO claude-workspaces.install claude-workspaces.desktop
   git commit -m "v0.1.0"
   git push
   ```

## Variante -git (HEAD)

Pra usuários que querem rodar HEAD direto, criar `claude-workspaces-git` separado
com `pkgver()` usando `git describe`. Não vou empurrar esse agora — primeiro
estabilizar a versão estável.
