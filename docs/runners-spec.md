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

## Como investigar (obrigatório antes de gerar)

NÃO gere comandos genéricos. NÃO chute. Inspecione cada pasta do
workspace ANTES de propor qualquer comando — o comando correto está
sempre nos arquivos de configuração.

### Passo 1 — Liste a raiz de cada pasta

Use Glob/LS pra identificar o stack pela presença de manifest:
`package.json`, `pom.xml`, `build.gradle`, `pyproject.toml`,
`Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, `Makefile`,
`docker-compose.yml`, `Dockerfile`, `.nvmrc`, `.tool-versions`,
`.python-version`, `mise.toml`, `asdf` config, `README.md`.

### Passo 2 — Leia o manifest e extraia o comando real

**Node/JS** (`package.json`):
- Em `scripts`, prefira `dev` > `start` > `serve`. Se houver `dev:watch`,
  `dev:web`, etc., escolha o mais específico ao stack.
- Detecte o package manager pelo lockfile: `pnpm-lock.yaml` → pnpm,
  `yarn.lock` → yarn, `bun.lockb` → bun, senão npm.
- Monorepo (`turbo.json`, `pnpm-workspace.yaml`, `nx.json`): use
  `pnpm --filter <pkg> dev` ou `turbo run dev --filter=<pkg>`.

**Java** (`pom.xml` / `build.gradle`):
- Maven com plugin embutido: `spring-boot-maven-plugin` → `mvn
  spring-boot:run`; `tomcat7-maven-plugin` → `mvn tomcat7:run`;
  `jetty-maven-plugin` → `mvn jetty:run`; `cargo-maven2-plugin` (Liferay)
  → `mvn cargo:run`. Se for `war` sem plugin embutido, use scripts
  externos (Glassfish/Tomcat/WildFly) com paths absolutos.
- Gradle: `bootRun`, `run`, `appRun` — prefira `./gradlew bootRun`.
- Versão do Java: leia `<maven.compiler.source>`, `<java.version>`,
  `sourceCompatibility`. Múltiplas versões na hint → case cada pasta
  e prefixe `JAVA_HOME=... PATH=$JAVA_HOME/bin:$PATH` no comando.

**Python** (`pyproject.toml` / `requirements.txt` / `manage.py`):
- Django (`manage.py` presente): `python manage.py runserver 0.0.0.0:8000`.
- FastAPI/Flask: cheque `[project.scripts]` ou `[tool.poetry.scripts]`;
  se houver `uvicorn`/`gunicorn` nas deps, infira o app path
  (`module:app`) de `main.py`/`app.py`.
- Prefira `.venv/bin/python`; senão `python` ou `uv run` (se há
  `uv.lock`).

**Outros**: Go → `go run ./cmd/<bin>`; Rust → `cargo run`; Ruby/Rails →
`bundle exec rails server`; PHP/Laravel → `php artisan serve`.

**Docker**: se o projeto roda primário via container, use
`docker compose up` (start) e `docker compose down` (stop).

### Passo 2.5 — Verifique o toolchain

Confirme com Bash que o runtime existe e descubra o caminho real:
`node -v`, `java -version` + `ls /usr/lib/jvm`, `python3 -V`,
`go version`, `cargo --version`, `dotnet --list-sdks`, `ruby -v`,
`php -v`, `docker --version`. App servers externos:
`which asadmin` / `ls /opt/glassfish*/bin/asadmin 2>/dev/null`,
`which catalina.sh`, `ls /opt/wildfly*/bin/standalone.sh 2>/dev/null`.

Se a ferramenta faltar, gere o runner com `enabled: false` e adicione
um sufixo `(faltando: <tool>)` ao `name`. Mencione no relato final.

Se o binário não está no PATH default (ex: Java 8 em
`/usr/lib/jvm/java-8-openjdk`), prefixe `JAVA_HOME=... PATH=...` no
`start_cmd` em vez de assumir PATH global.

### Passo 3 — Determine `cwd`

Padrão: pasta do workspace que tem o manifest. Em monorepo, pode ser
uma subpasta (`apps/web`, `packages/api`).

### Passo 4 — `stop_cmd` / `restart_cmd`

- Foreground (npm run dev, mvn spring-boot:run): deixe ambos vazios.
- Daemonizam (Glassfish, Tomcat externo, WildFly): use os scripts
  `asadmin`/`catalina.sh`/`standalone.sh` explicitamente.

## Formato de saída

Gere um JSON envelope com a chave `runners` (lista):

```json
{"runners": [ { ...config... } ]}
```

Nomeie cada runner de forma curta e específica (`web`, `api`,
`glassfish-ogpms`, `worker-emails`) — evite nomes genéricos como
"runner" ou "app".

Salve no caminho que o app indicar no prompt (criando diretórios pai
com `mkdir -p` se necessário). Depois informe:

1. Quais arquivos você leu e o que extraiu de cada um.
2. Que o usuário deve clicar em **↻ Recarregar runners** no header da
   aba Runners do claude-workspaces para importar.
