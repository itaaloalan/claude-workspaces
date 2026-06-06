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

## Menu do pill

Clique no pill pra abrir o menu:

- **🎯 Ir para a sessão do Claude** — foca o app no console daquele worktree
- **📂 Abrir pasta do worktree** — explorer no cwd do runner
- **💻 Abrir console do Claude aqui** — overlay com xterm.js espelhando o
  MESMO PTY do console do app (digite de qualquer lado, é a mesma sessão);
  abas extras com os LOGS dos runners do console + botão ↻ Reiniciar
- **↗ Console em janela separada** — mesmo espelho, em janela própria
  (fallback pra páginas com CSP que bloqueia iframe)
- **Mover ↖↗↙↘** — canto do pill, lembrado POR SISTEMA (host:porta)

## Como funciona / segurança

- O app empurra a cada 3s o mapa `porta → {workspace, runner, cwd}` pro
  servidor local; branch/worktree são resolvidos por cwd com cache.
- A extensão consulta o endpoint ao ativar/carregar abas localhost e
  aplica badge (4 letras da branch) + pill. App fechado → sem badge.
- Segurança: servidor só em 127.0.0.1; CORS restrito a origens
  localhost/extensão (site da internet não lê nada); checagem de Host
  (anti DNS-rebinding); `/console/*` e `/runner/restart` exigem token
  rotacionado a cada execução do app.
