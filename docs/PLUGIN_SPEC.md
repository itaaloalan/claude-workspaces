# Claude Workspaces — Plugin Spec v2.0

Este documento é a fonte da verdade para autores de plugins (humanos ou IA).
Plugins que violem qualquer regra deste documento serão rejeitados na validação.

> **Mudança vs v1**: handlers agora são `.py` (não `.ts`). O app é Python e
> executa plugins no mesmo runtime via `importlib`, sem ponte para outra linguagem.
> O modelo de permissões e o catálogo de eventos não mudaram.

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

**Não-objetivos (v2)**
- Marketplace remoto. Plugins moram em disco, versionados via git local.
- Acesso a APIs do sistema operacional além das declaradas.
- Hot-reload em produção (apenas em modo dev).
- Sandbox kernel-level (seccomp/namespaces). A garantia é por análise estática +
  contrato de API; o host roda single-user, é responsabilidade do usuário
  revisar antes de instalar.

## 2. Layout do bundle (obrigatório)

```
meu-plugin/
├── plugin.yaml          # manifesto, OBRIGATÓRIO
├── README.md            # descrição em PT-BR, OBRIGATÓRIO
├── src/                 # código Python (apenas .py)
│   ├── __init__.py      # pode ser vazio
│   ├── commands/        # 1 arquivo por comando
│   │   └── __init__.py
│   ├── hooks/           # 1 arquivo por hook
│   │   └── __init__.py
│   └── panels/          # 1 arquivo por painel
│       └── __init__.py
├── assets/              # ícones, imagens (svg/png)
└── tests/               # opcional mas recomendado, test_*.py
```

**Regras duras:**
- Nenhum arquivo `.js`/`.ts`/`.so`/`.pyc` no bundle (apenas `.py`).
- Sem `setup.py`, `pyproject.toml`, `requirements.txt` — dependências vêm do host.
- Sem `__pycache__/`, `.venv/`, `node_modules/`.
- Sem arquivos fora desses diretórios.
- Imports apenas relativos (`from .lib import ...`) ou do allowlist
  (`claude_workspaces.plugin_api` e Python stdlib seguro — seção 9).

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
  handler: string           # caminho ./src/commands/<arquivo>.py
  description: string

Hook:
  event: string             # ver catálogo seção 7
  handler: string           # caminho ./src/hooks/<arquivo>.py
  throttle-ms: number       # opcional, padrão 0, máx 60000
  debounce-ms: number       # opcional, exclusivo com throttle

Panel:
  id: string
  title: string
  slot: "sidebar-top" | "sidebar-bottom" | "workspace-tab"
  handler: string           # caminho ./src/panels/<arquivo>.py
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
4. Toda permissão declarada é usada (análise estática AST do código).
5. Toda chamada `ctx.*` no código tem permissão declarada.
6. Sem imports proibidos (seção 9).
7. README existe, tem mais de 100 caracteres, menciona o que o plugin faz.
8. Todo handler de command/hook é `async def handler(ctx, payload?)`; handler
   de panel é função síncrona que retorna `QWidget`.

## 4. Pontos de extensão

### 4.1 Commands

Aparecem na paleta global (Ctrl+P). Invocação síncrona pelo usuário.

```python
# src/commands/meu_comando.py
from claude_workspaces.plugin_api import CommandContext


async def handler(ctx: CommandContext) -> None:
    ws = await ctx.workspaces.current()
    await ctx.ui.notify(title="Olá", body=f"Workspace: {ws.name if ws else 'nenhum'}")
```

Tempo máximo de execução: **30 segundos**. Depois disso, host cancela.

Todo arquivo de handler deve exportar `async def handler(ctx)`.

### 4.2 Hooks

Reagem a eventos do app. Múltiplos plugins podem ouvir o mesmo evento.

```python
# src/hooks/on_status.py
from claude_workspaces.plugin_api import HookContext, SessionStatusChangedPayload


async def handler(ctx: HookContext, payload: SessionStatusChangedPayload) -> None:
    if payload.new_status == "awaiting-input" and payload.duration_ms > 300_000:
        await ctx.ui.notify(title="Sessão parada", body=payload.session_id)
```

Tempo máximo: **5 segundos**. Host **não** garante ordem entre hooks de plugins
diferentes para o mesmo evento.

### 4.3 Panels

Componentes renderizados como `QWidget` Qt. Diferente de commands/hooks, o
handler é uma factory **síncrona** que recebe o `PanelContext` e devolve o
widget. Toda I/O posterior é via `ctx.*`.

```python
# src/panels/stale.py
from claude_workspaces.plugin_api import PanelContext
from PySide6.QtWidgets import QListWidget, QVBoxLayout, QWidget


def handler(ctx: PanelContext) -> QWidget:
    root = QWidget()
    layout = QVBoxLayout(root)
    list_widget = QListWidget()
    layout.addWidget(list_widget)

    async def refresh(_payload: dict) -> None:
        sessions = await ctx.sessions.list(status="awaiting-input")
        list_widget.clear()
        for s in sessions:
            list_widget.addItem(s.id)

    ctx.on_event("session.status-changed", refresh)
    return root
```

## 5. API: o objeto `ctx`

Toda chamada é assíncrona (`async`) e retorna awaitable, exceto onde indicado.
Toda chamada é validada contra permissões antes de executar.

Os protocolos vivem em `claude_workspaces.plugin_api`.

### 5.1 Workspaces
```python
ctx.workspaces.list() -> list[Workspace]
ctx.workspaces.current() -> Workspace | None
ctx.workspaces.get(id: str) -> Workspace
```

### 5.2 Sessions
```python
ctx.sessions.list(*, status: str | None = None) -> list[Session]
ctx.sessions.get(id: str) -> Session
ctx.sessions.focus(id: str) -> None   # traz pra frente na UI
```

### 5.3 UI
```python
ctx.ui.notify(*, title: str, body: str, sound: bool = False) -> None
ctx.ui.badge(*, count: int | None = None) -> None
ctx.ui.toast(*, message: str, level: str = "info") -> None
```

### 5.4 Config
```python
ctx.config.get(key: str) -> Any
ctx.config.on_change(cb: Callable[[str, Any], None]) -> Unsubscribe  # síncrono
```

### 5.5 Storage (isolado por plugin)
```python
ctx.storage.get(key: str) -> Any | None
ctx.storage.set(key: str, value: Any) -> None
ctx.storage.delete(key: str) -> None
ctx.storage.clear() -> None
```
Limite: 10 MB total por plugin. Persistido em `<plugin>/.state/store.json`.

### 5.6 Filesystem (restrito ao declarado)
```python
ctx.fs.read(path: str) -> str
ctx.fs.write(path: str, content: str) -> None   # só com permissão
ctx.fs.list(path: str) -> list[str]
```

### 5.7 Network (restrito ao declarado)
```python
ctx.http.get(url: str, *, headers: dict | None = None) -> HttpResponse
ctx.http.post(url: str, *, body: bytes | str, headers: dict | None = None) -> HttpResponse
```

### 5.8 Log
```python
ctx.log.info(msg: str, **data) -> None      # síncronos
ctx.log.warn(msg: str, **data) -> None
ctx.log.error(msg: str, **data) -> None
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
| `session.created` | Nova sessão iniciada | `SessionCreatedPayload(session_id, workspace_id, created_at)` |
| `session.status-changed` | Status muda | `SessionStatusChangedPayload(session_id, old_status, new_status, duration_ms)` |
| `session.message-sent` | Usuário envia mensagem | `SessionMessageSentPayload(session_id, message_id, length)` |
| `session.completed` | Sessão termina | `SessionCompletedPayload(session_id, reason, duration_ms)` |
| `workspace.opened` | Usuário abre workspace | `WorkspaceOpenedPayload(workspace_id)` |
| `workspace.closed` | Workspace fechado | `WorkspaceClosedPayload(workspace_id)` |
| `commit.created` | Commit detectado | `CommitCreatedPayload(workspace_id, sha, message)` |
| `plugin.config-changed` | Config do próprio plugin mudou | `PluginConfigChangedPayload(key, old_value, new_value)` |

Status possíveis de sessão: `running`, `awaiting-input`, `idle`, `completed`, `error`.

**Para eventos de alta frequência** (`session.message-sent`), `throttle-ms` ou
`debounce-ms` é **obrigatório** no manifesto.

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
| `network.hosts` | lista de domínios | `ctx.http.*` |
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

1. `eval()`, `exec()`, `compile()`, ou `__import__()` dinâmico.
2. Import de módulos perigosos: `os` (exceto `os.path`), `sys`, `subprocess`,
   `socket`, `urllib.request`, `requests`, `httpx`, `multiprocessing`,
   `threading`, `ctypes`, `importlib`, `pkgutil`, `pickle`, `shelve`, `marshal`.
3. Import de pacote de terceiros fora do allowlist (atualmente apenas
   `claude_workspaces.plugin_api`, `PySide6` para panels, e a stdlib segura
   listada abaixo).
4. Acesso a atributos dunder de runtime: `__builtins__`, `__globals__`,
   `__import__`, `__class__.__subclasses__`, etc.
5. Loops sem condição de parada óbvia em handlers de evento.
6. Polling com intervalo menor que 1s (use hooks; `asyncio.sleep` < 1.0 em loop).
7. Strings codificadas em base64/hex que aparentem ser código.
8. Escrita em caminhos não-declarados via técnicas indiretas (`..`, symlinks).
9. Uso de `open()` direto (use `ctx.fs.*`).
10. Decoradores que modificam comportamento de imports/runtime.

**Stdlib segura permitida (allowlist):**
`asyncio`, `collections`, `contextlib`, `dataclasses`, `datetime`, `enum`,
`functools`, `itertools`, `json`, `math`, `re`, `string`, `textwrap`, `time`
(apenas `monotonic`, `time`; sem `sleep` em hot loop), `typing`, `os.path`,
`pathlib.PurePath` (sem `Path` que toca filesystem).

Validação faz **análise estática AST** antes do install final. Não há execução
em sandbox isolado (kernel-level) — o contrato é por API e revisão.

## 10. Convenções de qualidade

- **ID**: reverse-DNS, lowercase, hífens permitidos. Exemplo: `com.italo.sessao-watcher`.
- **Versão**: SemVer estrito. Breaking change = major bump.
- **README** deve conter, nesta ordem:
  1. O que o plugin faz (1 parágrafo).
  2. Permissões pedidas e por quê (uma linha por permissão).
  3. Configurações disponíveis.
  4. Exemplo de uso ou screenshot.
- **Testes**: pelo menos um por handler crítico. Use `tests/test_*.py` (pytest).
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
      handler: ./src/hooks/on_status.py

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

```python
# src/hooks/on_status.py
from claude_workspaces.plugin_api import HookContext, SessionStatusChangedPayload


async def handler(
    ctx: HookContext, payload: SessionStatusChangedPayload
) -> None:
    if payload.new_status != "awaiting-input":
        return

    threshold_min = await ctx.config.get("threshold_minutes")
    if payload.duration_ms < threshold_min * 60 * 1000:
        return

    session = await ctx.sessions.get(payload.session_id)
    await ctx.ui.notify(
        title="Sessão aguardando há muito tempo",
        body=f"{session.workspace_name}: {session.last_message or '(sem título)'}",
    )
```

### 11.2 Plugin de comando

```yaml
extensions:
  commands:
    - id: contar-sessoes
      title: "Contar sessões ativas"
      handler: ./src/commands/contar.py
      description: "Mostra quantas sessões estão rodando em todos workspaces"

permissions:
  filesystem:
    read: []
    write: []
  network:
    hosts: []
  notifications: true
  workspaces: all
```

```python
# src/commands/contar.py
from claude_workspaces.plugin_api import CommandContext


async def handler(ctx: CommandContext) -> None:
    sessions = await ctx.sessions.list(status="running")
    await ctx.ui.toast(message=f"{len(sessions)} sessões ativas", level="info")
```

## 12. Checklist para IA gerar plugin válido

Antes de retornar, a IA **deve** verificar mentalmente:

```
□ Manifesto tem todos campos obrigatórios da seção 3.1
□ id em reverse-DNS, único e descritivo
□ engine.claude-workspaces declarado com range
□ Pelo menos uma extensão declarada
□ Toda extensão referencia arquivo handler .py que será gerado
□ Todo handler de command/hook é `async def handler(ctx, payload?)`
□ Todo handler de panel é função síncrona que retorna QWidget
□ Toda permissão declarada é efetivamente usada no código
□ Nenhuma chamada ctx.* usa permissão não declarada
□ Nenhum import proibido (seção 9)
□ Nenhuma proibição da seção 9 violada
□ Eventos de alta frequência têm throttle/debounce
□ README em PT-BR com as 4 seções da seção 10
□ Pelo menos um teste por handler crítico
□ Decisões automáticas (sem perguntar ao usuário) listadas no campo `notes`
```

## 13. Formato da resposta da IA

Quando geração é solicitada, a IA retorna **um único objeto JSON**:

```json
{
  "manifest": "<conteúdo YAML como string>",
  "files": [
    { "path": "README.md", "content": "..." },
    { "path": "src/__init__.py", "content": "" },
    { "path": "src/hooks/__init__.py", "content": "" },
    { "path": "src/hooks/on_status.py", "content": "..." },
    { "path": "tests/test_on_status.py", "content": "..." }
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
    { "type": "modify", "path": "src/hooks/on_status.py", "content": "..." },
    { "type": "add", "path": "src/lib/format.py", "content": "..." },
    { "type": "delete", "path": "tests/test_old.py" }
  ],
  "manifest-changes": null,
  "notes": ["..."]
}
```

Se o patch falhar validação 2 vezes, host automaticamente pede **rewrite completo**
com o erro como contexto adicional.

## 14. Versionamento desta spec

Esta spec usa SemVer. Plugins declaram compatibilidade via `engine.claude-workspaces`.

- **Patch (2.0.x)**: clarificações, exemplos, sem mudança de regra.
- **Minor (2.x.0)**: novos eventos, novas APIs, novas permissões. Plugins antigos continuam válidos.
- **Major (x.0.0)**: breaking changes. Anunciado com 2 minor versions de antecedência. Deprecações listadas no CHANGELOG da spec.

**Mudança v1→v2**: handlers `.ts` → `.py`. Plugins v1 não são compatíveis com v2.

Histórico de mudanças vive em `PLUGIN_SPEC_CHANGELOG.md`.
