# Claude Workspaces — Plugin Spec v1.0

Este documento é a fonte da verdade para autores de plugins (humanos ou IA).
Plugins que violem qualquer regra deste documento serão rejeitados na validação.

## 0. Glossário rápido

- **Plugin**: bundle que estende o Claude Workspaces. Roda em sandbox isolado.
- **Bundle**: pasta com manifesto + código + assets, com layout fixo (seção 2).
- **Host**: o app Claude Workspaces.
- **Extensão**: capacidade que o plugin entrega (command, hook, painel, etc).
- **ctx**: objeto injetado em todo handler. Único caminho para falar com o host.

## 1. Objetivos e não-objetivos

**Objetivos**
- Permitir extensão segura do app sem recompilação.
- Permitir geração assistida por IA com taxa alta de plugin válido na primeira tentativa.
- Manter isolamento forte: um plugin que crasha não derruba nada além de si mesmo.

**Não-objetivos (v1)**
- Marketplace remoto. Plugins moram em disco, versionados via git local.
- Acesso a APIs do sistema operacional além das declaradas.
- Hot-reload em produção (apenas em modo dev).

## 2. Layout do bundle (obrigatório)

```
meu-plugin/
├── plugin.yaml          # manifesto, OBRIGATÓRIO
├── README.md            # descrição em PT-BR, OBRIGATÓRIO
├── src/                 # código TypeScript (apenas .ts)
│   ├── commands/        # 1 arquivo por comando
│   ├── hooks/           # 1 arquivo por hook
│   └── panels/          # 1 arquivo por painel
├── assets/              # ícones, imagens (svg/png)
└── tests/               # opcional mas recomendado, *.test.ts
```

**Regras duras:**
- Nenhum arquivo `.js` no bundle (apenas `.ts`, transpilado pelo host).
- Sem `node_modules/`, `package.json`, `package-lock.json`.
- Sem arquivos fora desses diretórios.
- Imports apenas relativos (`./`) ou do allowlist de bibliotecas padrão.

## 3. Manifesto (`plugin.yaml`)

### 3.1 Schema completo

```yaml
# Identidade (todos obrigatórios)
id: string                  # reverse-DNS, regex: ^[a-z0-9]+(\.[a-z0-9-]+)+$
name: string                # nome de exibição
version: string             # SemVer estrito (1.2.3)
author: string
description: string         # máx 200 caracteres
license: string             # SPDX ID (ex: MIT, Apache-2.0)

# Opcionais
homepage: string            # URL https://
icon: string                # caminho relativo (ex: ./assets/icon.svg)

# Compatibilidade (obrigatório)
engine:
  claude-workspaces: string # range SemVer (ex: ">=1.0.0 <2.0.0")

# Pelo menos uma extensão (obrigatório)
extensions:
  commands: [Command]
  hooks: [Hook]
  panels: [Panel]

# Permissões (obrigatório, mesmo que vazio)
permissions:
  filesystem:
    read: [string]          # globs absolutos ou com ~
    write: [string]
  network:
    hosts: [string]         # domínios exatos, sem wildcards
  notifications: boolean
  workspaces: "all" | [string]  # IDs de workspaces ou "all"

# Configuração exposta ao usuário (opcional)
config: [ConfigField]

# Metadados (preenchidos pelo host no install, não enviar)
# generated-by, generated-at, checksum
```

### 3.2 Tipos

```yaml
Command:
  id: string                # único dentro do plugin, regex: ^[a-z][a-z0-9-]*$
  title: string             # aparece na paleta de comandos
  handler: string           # caminho ./src/commands/<arquivo>.ts
  description: string

Hook:
  event: string             # ver catálogo seção 7
  handler: string           # caminho ./src/hooks/<arquivo>.ts
  throttle-ms: number       # opcional, padrão 0, máx 60000
  debounce-ms: number       # opcional, exclusivo com throttle

Panel:
  id: string
  title: string
  slot: "sidebar-top" | "sidebar-bottom" | "workspace-tab"
  handler: string           # caminho ./src/panels/<arquivo>.ts
  icon: string              # caminho relativo

ConfigField:
  key: string               # snake_case
  type: "string" | "integer" | "boolean" | "enum"
  default: any
  label: string             # PT-BR
  required: boolean         # padrão false
  # type-specific:
  min/max: number           # para integer
  options: [string]         # para enum
  multiline: boolean        # para string
```

### 3.3 Validações automáticas

Antes do install, host verifica:

1. Schema YAML válido e todos campos obrigatórios presentes.
2. `id` único entre plugins instalados.
3. Todo `handler` referencia arquivo existente no bundle.
4. Toda permissão declarada é usada (análise estática de imports/chamadas).
5. Toda chamada `ctx.*` no código tem permissão declarada.
6. Sem imports proibidos (seção 9).
7. README existe, tem mais de 100 caracteres, menciona o que o plugin faz.

## 4. Pontos de extensão

### 4.1 Commands

Aparecem na paleta global (Ctrl+P). Invocação síncrona pelo usuário.

```typescript
// src/commands/meu-comando.ts
import { CommandContext } from "@claude-workspaces/api";

export default async function(ctx: CommandContext): Promise<void> {
  const ws = await ctx.workspaces.current();
  await ctx.ui.notify({ title: "Olá", body: `Workspace: ${ws.name}` });
}
```

Tempo máximo de execução: **30 segundos**. Depois disso, host cancela.

### 4.2 Hooks

Reagem a eventos do app. Múltiplos plugins podem ouvir o mesmo evento.

```typescript
// src/hooks/on-status.ts
import { HookContext, SessionStatusChangedPayload } from "@claude-workspaces/api";

export default async function(
  ctx: HookContext,
  payload: SessionStatusChangedPayload
): Promise<void> {
  if (payload.newStatus === "awaiting-input" && payload.durationMs > 300000) {
    await ctx.ui.notify({ title: "Sessão parada", body: payload.sessionId });
  }
}
```

Tempo máximo: **5 segundos**. Host **não** garante ordem entre hooks de plugins diferentes para o mesmo evento.

### 4.3 Panels

Componentes renderizados em iframe sandbox. Comunicação via API `ctx.ui.panel`.

```typescript
// src/panels/stale.ts
import { PanelContext } from "@claude-workspaces/api";

export default function(ctx: PanelContext) {
  ctx.render(({ html, useState, useEvent }) => {
    const [sessions, setSessions] = useState<Session[]>([]);

    useEvent("session.status-changed", async () => {
      const all = await ctx.sessions.list({ status: "awaiting-input" });
      setSessions(all);
    });

    return html`
      <ul>
        ${sessions.map(s => html`<li>${s.id}</li>`)}
      </ul>
    `;
  });
}
```

Painéis **não** podem fazer fetch direto. Toda I/O passa por `ctx.*`.

## 5. API: o objeto `ctx`

Toda chamada é assíncrona, retorna Promise. Toda chamada é validada contra permissões antes de executar.

### 5.1 Workspaces
```typescript
ctx.workspaces.list(): Promise<Workspace[]>
ctx.workspaces.current(): Promise<Workspace | null>
ctx.workspaces.get(id: string): Promise<Workspace>
```

### 5.2 Sessions
```typescript
ctx.sessions.list(filter?: SessionFilter): Promise<Session[]>
ctx.sessions.get(id: string): Promise<Session>
ctx.sessions.focus(id: string): Promise<void>     // traz pra frente na UI
```

### 5.3 UI
```typescript
ctx.ui.notify(opts: { title, body, sound?, actions? }): Promise<void>
ctx.ui.badge(opts: { count?, color? }): Promise<void>  // badge no item do plugin
ctx.ui.toast(opts: { message, level }): Promise<void>
```

### 5.4 Config
```typescript
ctx.config.get<T>(key: string): Promise<T>
ctx.config.onChange(cb: (key, newValue) => void): Unsubscribe
```

### 5.5 Storage (isolado por plugin)
```typescript
ctx.storage.get<T>(key: string): Promise<T | null>
ctx.storage.set(key: string, value: any): Promise<void>
ctx.storage.delete(key: string): Promise<void>
ctx.storage.clear(): Promise<void>
```
Limite: 10 MB total por plugin. Persistido em `<plugin>/.state/`.

### 5.6 Filesystem (restrito ao declarado)
```typescript
ctx.fs.read(path: string): Promise<string>
ctx.fs.write(path: string, content: string): Promise<void>   // só com permissão
ctx.fs.list(path: string): Promise<string[]>
```

### 5.7 Network (restrito ao declarado)
```typescript
ctx.http.fetch(url: string, opts?: FetchOpts): Promise<Response>
```

### 5.8 Log
```typescript
ctx.log.info|warn|error(msg: string, data?: object): void
```
Logs vão para `<plugin>/.logs/YYYY-MM-DD.log`. Visíveis na UI do plugin.

## 6. Não disponível no `ctx`

Por design, plugins **não podem**:
- Iniciar sessões do Claude (só observar).
- Modificar arquivos de outros plugins.
- Ler git history de workspaces (privacidade).
- Acessar variáveis de ambiente do host.
- Modificar a UI fora dos slots declarados.
- Falar com outros plugins diretamente (use eventos).

Se um plugin precisa de algo aqui, é sinal de que o app precisa expor uma API nova — não que o plugin deva contornar.

## 7. Catálogo de eventos

| Evento | Disparo | Payload |
|--------|---------|---------|
| `session.created` | Nova sessão iniciada | `{ sessionId, workspaceId, createdAt }` |
| `session.status-changed` | Status muda | `{ sessionId, oldStatus, newStatus, durationMs }` |
| `session.message-sent` | Usuário envia mensagem | `{ sessionId, messageId, length }` |
| `session.completed` | Sessão termina | `{ sessionId, reason, durationMs }` |
| `workspace.opened` | Usuário abre workspace | `{ workspaceId }` |
| `workspace.closed` | Workspace fechado | `{ workspaceId }` |
| `commit.created` | Commit detectado | `{ workspaceId, sha, message }` |
| `plugin.config-changed` | Config do próprio plugin mudou | `{ key, oldValue, newValue }` |

Status possíveis de sessão: `running`, `awaiting-input`, `idle`, `completed`, `error`.

**Para eventos de alta frequência** (`session.message-sent`), `throttle-ms` ou `debounce-ms` é **obrigatório** no manifesto.

## 8. Modelo de permissões

### 8.1 Princípios
- Toda capacidade exige declaração explícita no manifesto.
- Usuário aprova no install. Pode revogar a qualquer momento.
- Pedir permissão em runtime **não existe**. Não declarou, não pode.
- Princípio do menor privilégio: peça o mínimo, justifique no README.

### 8.2 Permissões disponíveis

| Permissão | Forma | Necessária para |
|-----------|-------|-----------------|
| `filesystem.read` | lista de globs | `ctx.fs.read`, `ctx.fs.list` |
| `filesystem.write` | lista de globs | `ctx.fs.write` |
| `network.hosts` | lista de domínios | `ctx.http.fetch` |
| `notifications` | boolean | `ctx.ui.notify`, `ctx.ui.toast` |
| `workspaces` | `all` ou lista | acessar workspaces fora dos listados |

### 8.3 O que **não** precisa de permissão
- `ctx.storage.*` (isolado por plugin)
- `ctx.config.*` (próprio plugin)
- `ctx.log.*`
- `ctx.ui.badge` (só afeta o próprio plugin)
- Inscrição em eventos (qualquer plugin pode ouvir)

## 9. Regras de segurança (proibições duras)

Plugin será **rejeitado** se contiver:

1. `eval()`, `new Function()`, ou equivalentes.
2. Import de `node:child_process`, `node:fs`, `node:net`, `node:http`, ou qualquer módulo nativo.
3. Import de pacote npm fora do allowlist (atualmente: nenhum — apenas stdlib).
4. Acesso direto a `globalThis` ou `window` além do declarado pela API.
5. Loops sem condição de parada óbvia em handlers de evento.
6. Polling com intervalo menor que 1000ms (use hooks).
7. Strings codificadas em base64/hex que aparentem ser código.
8. Escrita em caminhos não-declarados via técnicas indiretas (symlinks, `..`).
9. Tentativa de spawn de processo.
10. Uso de `WebAssembly` (v1 não suporta).

Validação faz **análise estática + execução em sandbox sem rede** antes do install final.

## 10. Convenções de qualidade

- **ID**: reverse-DNS, lowercase, hífens permitidos. Exemplo: `com.italo.sessao-watcher`.
- **Versão**: SemVer estrito. Breaking change = major bump.
- **README** deve conter, nesta ordem:
  1. O que o plugin faz (1 parágrafo).
  2. Permissões pedidas e por quê (uma linha por permissão).
  3. Configurações disponíveis.
  4. Exemplo de uso ou screenshot.
- **Testes**: pelo menos um por handler crítico. Use `tests/*.test.ts`.
- **i18n**: textos em PT-BR. Não traduza automaticamente.
- **Erros**: capture, logue via `ctx.log.error`, não relance em handlers de hook.

## 11. Exemplos completos

### 11.1 Plugin de hook + notificação

```yaml
# plugin.yaml
id: com.exemplo.sessao-watcher
name: Sessão Watcher
version: 0.1.0
author: exemplo
description: Notifica quando sessões ficam aguardando input por muito tempo
license: MIT
engine:
  claude-workspaces: ">=1.0.0 <2.0.0"

extensions:
  hooks:
    - event: session.status-changed
      handler: ./src/hooks/on-status.ts

permissions:
  filesystem:
    read: []
    write: []
  network:
    hosts: []
  notifications: true
  workspaces: all

config:
  - key: threshold_minutes
    type: integer
    default: 5
    min: 1
    max: 60
    label: "Considerar parada após (min)"
```

```typescript
// src/hooks/on-status.ts
import { HookContext, SessionStatusChangedPayload } from "@claude-workspaces/api";

export default async function(
  ctx: HookContext,
  payload: SessionStatusChangedPayload
): Promise<void> {
  if (payload.newStatus !== "awaiting-input") return;

  const thresholdMin = await ctx.config.get<number>("threshold_minutes");
  if (payload.durationMs < thresholdMin * 60 * 1000) return;

  const session = await ctx.sessions.get(payload.sessionId);
  await ctx.ui.notify({
    title: "Sessão aguardando há muito tempo",
    body: `${session.workspaceName}: ${session.lastMessage ?? "(sem título)"}`,
    actions: [{ id: "focus", label: "Abrir" }]
  });
}
```

### 11.2 Plugin de comando

```yaml
extensions:
  commands:
    - id: contar-sessoes
      title: "Contar sessões ativas"
      handler: ./src/commands/contar.ts
      description: "Mostra quantas sessões estão rodando em todos workspaces"

permissions:
  workspaces: all
  notifications: true
```

```typescript
// src/commands/contar.ts
import { CommandContext } from "@claude-workspaces/api";

export default async function(ctx: CommandContext): Promise<void> {
  const sessions = await ctx.sessions.list({ status: "running" });
  await ctx.ui.toast({
    message: `${sessions.length} sessões ativas`,
    level: "info"
  });
}
```

## 12. Checklist para IA gerar plugin válido

Antes de retornar, a IA **deve** verificar mentalmente:

```
□ Manifesto tem todos campos obrigatórios da seção 3.1
□ id em reverse-DNS, único e descritivo
□ engine.claude-workspaces declarado com range
□ Pelo menos uma extensão declarada
□ Toda extensão referencia arquivo handler que será gerado
□ Toda permissão declarada é efetivamente usada no código
□ Nenhuma chamada ctx.* usa permissão não declarada
□ Nenhum import proibido (seção 9)
□ Nenhuma proibição da seção 9 violada
□ Eventos de alta frequência têm throttle/debounce
□ README em PT-BR com as 4 seções da seção 10
□ Pelo menos um teste por handler crítico
□ Decisões automáticas (sem perguntar ao usuário) listadas no campo `notes` da resposta
```

## 13. Formato da resposta da IA

Quando geração é solicitada, a IA retorna **um único objeto JSON**:

```json
{
  "manifest": "<conteúdo YAML como string>",
  "files": [
    { "path": "README.md", "content": "..." },
    { "path": "src/hooks/on-status.ts", "content": "..." },
    { "path": "tests/on-status.test.ts", "content": "..." }
  ],
  "notes": [
    "Assumi threshold padrão de 5min — configurável pelo usuário.",
    "Não inclui som de notificação porque a descrição não pediu."
  ]
}
```

Para edições (patches), o formato é:

```json
{
  "operations": [
    { "type": "modify", "path": "src/hooks/on-status.ts", "content": "..." },
    { "type": "add", "path": "src/utils/format.ts", "content": "..." },
    { "type": "delete", "path": "tests/old.test.ts" }
  ],
  "manifest-changes": null,
  "notes": ["..."]
}
```

Se o patch falhar validação 2 vezes, host automaticamente pede **rewrite completo** com o erro como contexto adicional.

## 14. Versionamento desta spec

Esta spec usa SemVer. Plugins declaram compatibilidade via `engine.claude-workspaces`.

- **Patch (1.0.x)**: clarificações, exemplos, sem mudança de regra.
- **Minor (1.x.0)**: novos eventos, novas APIs, novas permissões. Plugins antigos continuam válidos.
- **Major (x.0.0)**: breaking changes. Anunciado com 2 minor versions de antecedência. Deprecações listadas no CHANGELOG da spec.

Histórico de mudanças vive em `PLUGIN_SPEC_CHANGELOG.md`.
