# Claude Workspaces — Indicador de Worktree (extensão Chrome)

Mostra **badge** no ícone e uma **faixa no topo da página** quando a aba
`localhost:<porta>` pertence a um runner do claude-workspaces:

- 🟧 **laranja** — o runner roda num **worktree** isolado (`🌿 branch — worktree · map / web`)
- 🟩 **verde** — repo principal

Os dados vêm do endpoint local do app (`http://127.0.0.1:43210/state.json`,
ligado por padrão — Settings → "browser_state_server_enabled").

## Instalação (load unpacked)

1. Abra `chrome://extensions`
2. Ative o **Modo do desenvolvedor** (canto superior direito)
3. **Carregar sem compactação** → selecione esta pasta (`chrome-extension/`)

Funciona em Chrome/Chromium/Brave/Edge. A faixa tem um ✕ pra esconder
na aba atual; o badge no ícone permanece.

## Como funciona

- O app empurra a cada 3s o mapa `porta → {workspace, runner, cwd}` pro
  servidor local; branch/worktree são resolvidos por cwd com cache.
- A extensão consulta o endpoint ao ativar/carregar abas localhost e
  aplica badge (4 letras da branch) + faixa. App fechado → sem badge.
