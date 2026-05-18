# Runners — Spec para geração via Claude

Um **Runner** é um processo de longa duração associado a um workspace
(servidor web, API, container Glassfish, etc.). O `claude-workspaces`
roda cada runner num PTY próprio e mostra o log em tempo real numa aba
dedicada da seção "Runners".

Esta spec é o contrato que o Claude deve seguir ao gerar um
`RunnerConfig` em JSON. **Leia este arquivo antes de responder.**

## Formato

```json
{
  "name": "web",
  "start_cmd": "npm run dev",
  "stop_cmd": "",
  "restart_cmd": "",
  "cwd": "",
  "enabled": true
}
```

- `name` — identificador curto exibido na aba (ex: `web`, `api`, `camera`).
- `start_cmd` — comando shell que **inicia** o processo. Deve permanecer
  em foreground sempre que possível (assim o app captura logs e detecta
  saída). Roda via `bash -lc <start_cmd>`.
- `stop_cmd` — opcional. Comando que **para** o processo de forma graciosa
  (ex: `asadmin stop-domain`). Vazio → app manda SIGHUP no PTY (suficiente
  para a maioria dos processos foreground).
- `restart_cmd` — opcional. Comando que **reinicia** (típico: redeploy +
  restart). Vazio → app executa stop seguido de start.
- `cwd` — opcional. Caminho absoluto. Vazio → primeira pasta do workspace.
- `enabled` — se `true`, é incluído quando o usuário clica "Rodar todos".

## Convenções

1. **Logs em stdout/stderr**: o app captura tudo que sai no PTY. Não use
   redirecionamento para arquivo (`>> /tmp/log`) — o usuário perde a visão.
2. **Foreground sempre que possível**: `npm run dev` ✓, `node server.js` ✓,
   `python -m uvicorn ...` ✓. Daemons que se desanexam (systemd, nohup,
   detach próprio do Glassfish) precisam de `stop_cmd`/`restart_cmd`
   explícitos para o app conseguir orquestrar.
3. **Sem `cd` no início** do comando — use o campo `cwd`. Comandos
   compostos com `&&` continuam ok.
4. **SIGHUP-friendly**: processos que reagem a SIGHUP encerrando limpamente
   não precisam de `stop_cmd`.

## Exemplos

### Vite/Next.js dev server

```json
{
  "name": "web",
  "start_cmd": "npm run dev",
  "stop_cmd": "",
  "restart_cmd": "",
  "cwd": "",
  "enabled": true
}
```

### API Python (uvicorn)

```json
{
  "name": "api",
  "start_cmd": "python -m uvicorn app.main:app --reload --port 8000",
  "stop_cmd": "",
  "restart_cmd": "",
  "cwd": "",
  "enabled": true
}
```

### Glassfish (precisa de stop/restart explícitos)

```json
{
  "name": "glassfish",
  "start_cmd": "asadmin start-domain --verbose domain1",
  "stop_cmd": "asadmin stop-domain domain1",
  "restart_cmd": "asadmin redeploy --name=ogpms target/ogpms.war && asadmin restart-domain domain1",
  "cwd": "",
  "enabled": true
}
```

### Emulador Android para "mobile"

```json
{
  "name": "mobile",
  "start_cmd": "emulator -avd Pixel_6_API_34 -no-snapshot-load",
  "stop_cmd": "adb emu kill",
  "restart_cmd": "",
  "cwd": "",
  "enabled": false
}
```

## Quando responder

Após ler esta spec, devolva **apenas o JSON** do RunnerConfig — sem
cercas markdown, sem prefácio, sem explicações. O usuário vai copiar e
colar diretamente no diálogo de edição do runner.
