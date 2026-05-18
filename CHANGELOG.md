# Changelog

Todas as mudanças relevantes neste projeto são documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto segue [versionamento semântico](https://semver.org/lang/pt-BR/) pragmático
(pré-1.0: `minor` para features visíveis, `patch` para correções/refactors).

## [0.18.10] — 2026-05-18

### Corrigido
- **Item do console expande quando tem runners**: o grupo "Runners
  console" estava sendo criado corretamente como filho do item do
  console, mas o `_install_console_runner_children` forçava
  `term_item.setExpanded(False)` no final, escondendo o grupo recém
  adicionado dentro de um console colapsado. Resultado: o painel
  "Runners (console)" aparecia com os runners, mas a sidebar parecia
  vazia. Agora o item de console é expandido sempre que tem runners
  no escopo, deixando o grupo visível por default.
- **Ordem das abas sincroniza com a sidebar**: arrastar abas de
  runner no painel (workspace ou console) agora persiste a nova
  ordem em `ws.runners`, mantendo as posições relativas dos runners
  fora de escopo. Antes, ao adicionar um novo runner o
  `_refresh_from_workspace` recriava as abas na ordem original do
  workspace e a ordenação manual sumia — e a sidebar mostrava uma
  ordem ainda diferente. Agora painel e sidebar concordam.

## [0.18.9] — 2026-05-18

### Corrigido
- **Sidebar lê os runners diretamente da RunnerArea do console**:
  `_install_console_runner_children` parou de re-filtrar runners por
  `console_session_id` (que diverge da `RunnerArea` quando o sid muda
  durante a sessão) e agora pega exatamente o conjunto que a area já
  exibe via `runners_in_scope()`. Garante paridade visual entre o
  painel "Runners (console)" e o grupo "Runners console" da sidebar —
  o que aparece num aparece no outro.

## [0.18.8] — 2026-05-18

### Corrigido
- **"Runners console" finalmente aparece na sidebar após restaurar**:
  `_ensure_terminal_runner_panel` agora dispara um
  `_install_console_runner_children` no fim, usando o `term_item` do
  console correspondente. Cobre a corrida em que `_add_terminal_child`
  rodou antes do `_claude_resume_id` propagar e marcou o grupo com
  pending key — agora, assim que a RunnerArea é criada (auto no
  restore ou manual via ▤ Runners), o grupo é re-instalado e os
  runners viram children visíveis do item do console.

## [0.18.7] — 2026-05-18

### Corrigido
- **Runners do console "sumiam" ao reabrir o app**: os runners
  persistidos (com `console_session_id`) já existiam no
  `workspaces.json` o tempo todo, mas a `RunnerArea` do console era
  criada só on-demand (no clique em ▤ Runners). Como o sid da area é
  usado pra ligar o grupo "Runners console" da sidebar, sem area não
  havia ligação. Agora, ao restaurar uma sessão via `--resume`, o app
  cria automaticamente a `RunnerArea` se existir ≥1 runner com sid
  matching — runners aparecem na sidebar e na aba "Runners (console)"
  já no primeiro paint, sem precisar clicar em nada.

## [0.18.6] — 2026-05-18

### Corrigido
- **"Runners console" agora aparece ao selecionar o workspace**:
  `_sync_terminal_for` ganha um `_refresh_runner_children` no fim, que
  re-instala os runner-children de cada console sempre que o user
  carrega o workspace. Cobre o cenário em que o `claimed_session_id`
  do terminal só foi resolvido depois do primeiro install (sessão
  fresca cujo JSONL apareceu tarde), deixando o grupo "Runners
  console" sem children até esse refresh.

## [0.18.5] — 2026-05-18

### Corrigido
- **Runners do console não apareciam na sidebar após "Copiar do
  workspace"**: `_install_console_runner_children` filtrava só pelo
  `claimed_session_id` do terminal, mas a `RunnerArea` podia ter sido
  criada com a chave pending e os runners stampados com ela enquanto o
  session_id real ainda não tinha chegado. Agora também aceita o sid
  da `RunnerArea` existente — qualquer match liga o runner ao
  "Runners console" do item.

## [0.18.4] — 2026-05-18

### Alterado
- **Clique simples no runner abre o log**: clicar uma vez num
  runner-child da sidebar agora já abre o painel "Runners" no console
  do runner (antes era só double-click/Enter). Resolve o escopo
  automaticamente — workspace-scope vai pra "Runners workspace",
  console-scope vai pra "Runners (console)" do console dono (cria a
  RunnerArea sob demanda se ainda não existia).

## [0.18.3] — 2026-05-18

### Adicionado
- **"↗ Copiar do workspace" no painel de runners do console**: novo
  botão no header da `RunnerArea` quando ela está em escopo de console
  — abre um menu listando os runners workspace-scoped e permite copiar
  um (ou "Copiar todos") pro escopo do console (id novo,
  `console_session_id` stampado). Colisão por nome dentro do escopo
  substitui o existente, igual ao merge do `import_runners`. Antes,
  pra reaproveitar um runner do workspace num console era preciso
  exportar/importar JSON.

## [0.18.2] — 2026-05-18

### Corrigido
- **Chevron ▾/▸ do grupo de runners agora colapsa de verdade**: o
  callback do botão recebia o `bool checked` emitido pelo `clicked`
  do `QPushButton` no lugar do default keyword-arg `g=group`, então
  `g` virava `False` e o `setExpanded` morria silenciosamente. Aceita
  args extras agora.

## [0.18.1] — 2026-05-18

### Corrigido
- **"Abrir Claude" agora foca a aba "Terminal"**: ao lançar um console
  pelo botão "Abrir Claude" (ou "Abrir Terminal") com a bottom tab
  ativa sendo "Runners workspace" ou "Runners (console)", o app já
  troca pra "Terminal" pra mostrar o terminal recém-criado. Antes
  o terminal era criado mas ficava invisível atrás da tab errada.

### Alterado
- **Placeholder de "Runners (console)" mais claro**: o texto agora
  diz onde fica o botão ▤ Runners (na barra do terminal) em vez de
  só citar o ícone.

## [0.18.0] — 2026-05-18

### Adicionado
- **Diálogo de "Trocar branch" com filtro incremental**: no menu de
  contexto do repo, "⎇ Trocar branch…" agora abre um picker com
  campo de busca e lista navegável por setas/Enter. Antes era um
  submenu plano que ficava impossível de operar em repos com muitas
  branches (rolagem infinita, sem busca).

## [0.17.1] — 2026-05-18

### Alterado
- **Botão ▾/▸ no header dos grupos de runners**: cada header
  "Runners workspace" / "Runners console" ganhou um chevron explícito
  pra recolher/expandir o grupo, no mesmo padrão do header do
  workspace. Antes a única forma era pela seta nativa da tree.

## [0.17.0] — 2026-05-18

### Alterado
- **Runners agrupados na sidebar sob header colapsável**: os runners
  agora aparecem aninhados sob um header dedicado — "Runners workspace"
  como filho do item do workspace e "Runners console" como filho de
  cada item de console. O header só é criado quando existe ao menos um
  runner naquele escopo (sem runners → sem header, sem ruído). Cada
  header tem um botão `＋` que abre o menu "Em branco / Gerar com
  Claude" no escopo correto — pra criar runner de console agora basta
  expandir o console na sidebar e clicar no `＋` ao lado de "Runners
  console" (antes só dava pelo `▤ Runners` na toolbar do terminal).

## [0.16.0] — 2026-05-18

### Alterado
- **Localizar arquivo movido pra sidebar + modal**: o input "Localizar
  arquivo" sai do painel de detalhes do workspace (direita) e vira
  uma caixa compacta na sidebar (esquerda), logo acima do botão
  "＋ Novo Workspace". Enter dispara um modal `FileFinderDialog`
  (720×480) com a lista de resultados em tela cheia, usando as
  pastas do workspace atualmente selecionado. Double-click / Editar
  abre no editor configurado e fecha o modal. Mais espaço pros
  resultados e acesso global (não depende da view atual).

## [0.15.0] — 2026-05-18

### Alterado
- **Runners de console viraram top tab no painel inferior**: a antiga
  aba "Runners" foi renomeada pra "Runners workspace" e ganhou uma
  nova vizinha — "Runners (console)" — que mostra o painel de runners
  do console (terminal) atualmente focado. O painel deixa de ser
  embutido dentro do TerminalWidget (splitter vertical xterm+runners)
  e passa a viver no `_bottom_tabs` ao lado do Terminal. O botão
  `▤ Runners` na toolbar do console foca a aba; trocar de console
  (terminal_host ou tabs.currentChanged) sincroniza automaticamente
  qual painel aparece. Fecha o terminal → o painel correspondente é
  removido do stack e destruído. Mais espaço vertical pro xterm e
  comportamento de descoberta consistente com os runners do workspace.

## [0.14.0] — 2026-05-18

### Alterado
- **Runners aninhados sob o console na sidebar**: runners com escopo
  de console (`console_session_id` setado) deixam de aparecer flat
  embaixo do workspace e passam a ser filhos do item do console
  correspondente — o nó do console fica colapsável (seta expand/recolhe)
  e começa recolhido por default. Runners workspace-scope continuam
  como filhos diretos do workspace (footer). Elimina o efeito de
  "lista duplicada" quando vários consoles compartilham o workspace
  e deixa claro a qual console cada runner pertence. Toggle pela
  sidebar (▶/■) procura o runner tanto na RunnerArea do workspace
  quanto nas RunnerAreas embutidas dos consoles.

## [0.13.0] — 2026-05-18

### Adicionado
- **Runners por console**: cada aba Claude (console) ganha um painel
  embutido de runners próprio, acessível pelo botão `▤ Runners` na
  toolbar do terminal (splitter vertical: xterm em cima, painel embaixo).
  Runners criados ali pertencem só àquele console — permite rodar
  várias instâncias do mesmo serviço com branches/portas diferentes
  em consoles paralelos, sem conflito com o painel inferior do
  workspace. Persistência via `console_session_id` do `RunnerConfig`,
  apontando pro `session_id` do Claude (resume re-vincula os runners
  do console automaticamente). Runners sem `console_session_id`
  continuam no painel inferior do workspace (default, antigo).
  Import/export e merge por nome respeitam o escopo (workspace exporta
  só workspace; console exporta só daquele console, sem persistir o
  id da sessão pra ser portável).

## [0.12.0] — 2026-05-18

### Adicionado
- **Encerrar/remover console pelo menu de contexto da sidebar**: no item
  de um console terminal, o menu de contexto ganha "✖ Encerrar/remover
  console", que encerra o processo (se rodando) e remove a aba do
  terminal. Para consoles ainda rodando aparece após as ações de Claude;
  para consoles já parados é a única ação disponível (antes o menu nem
  aparecia para esses).

## [0.11.0] — 2026-05-18

### Adicionado
- **Trocar branch pelo menu de contexto do repo**: no painel Git, clique
  direito num repo abre submenu "⎇ Trocar branch" com a lista de
  branches locais (lazy load via `git branch`). A branch atual aparece
  marcada com `●` e desabilitada; selecionar outra dispara
  `git checkout <branch>` e refresca o painel. Erros do checkout
  (working tree sujo com conflito, branch inexistente etc.) abrem
  QMessageBox com o stderr do git.

## [0.10.0] — 2026-05-18

### Adicionado
- **Localizador de arquivos no painel do workspace**: caixa de busca
  acima das sessões com lista de resultados e botões "Abrir"
  (xdg-open no app padrão) e "Editar" (editor configurado). Usa `fd`
  quando disponível (respeita `.gitignore` e ignora dotfiles); fallback
  puro Python pula `.git`, `node_modules`, `.venv` etc. Double-click
  abre direto no editor. Limitado a 200 resultados e a busca roda
  só nas pastas do workspace selecionado.

## [0.9.2] — 2026-05-18

### Corrigido
- **Stop do runner ficava travado em "rodando"**: `PtySession.terminate()`
  fechava o FD e zerava o pid mas não emitia `finished`, então a UI
  do RunnerWidget e o footer da sidebar nunca saíam do estado
  "running" (botão Stop habilitado, dot verde). Agora emite `finished`
  após o cleanup, e o sinal sempre dispara mesmo quando o stop é
  iniciado pelo app.
- **`npm start` / `ng serve` continuavam rodando após Stop**: o sinal
  era enviado só pro PID líder (bash/npm), deixando o `node` filho
  segurando a porta. Agora `terminate()` usa `os.killpg(SIGTERM)` —
  como `pty.fork()` coloca o filho como session leader, a PID também
  é PGID e o SIGTERM atinge todos os descendentes em um sweep.

## [0.9.1] — 2026-05-18

### Adicionado
- **Botão 📋 Copiar log** no toolbar de cada runner: copia o log atual
  (até ~1MB, com ANSI strip-ado) pro clipboard. Útil pra colar em
  bug reports ou jogar pro Claude analisar.

### Corrigido
- **Botão "Remover" do runner desproporcional**: largura fixada em
  36px pra ficar do tamanho do ícone 🗑, parando de competir com os
  botões de texto.

## [0.9.0] — 2026-05-18

### Adicionado
- **Footer de runners por workspace na sidebar**: cada runner aparece
  como uma linha compacta no fim do bloco do workspace, com nome, dot
  de estado (verde rodando, vermelho erro, cinza parado/idle) e botão
  ▶/■ pra iniciar/parar direto da sidebar — sem precisar abrir a aba
  Runners. Double-click na linha abre a aba Runners e foca o runner
  correspondente. RunnerArea é criada sob demanda quando o ▶ é
  clicado, então workspaces nunca abertos não pagam o custo do
  QWebEngineView até o usuário interagir.

## [0.8.4] — 2026-05-18

### Mudado
- **Ícone de "Ocioso" na sidebar mais discreto**: trocado `❚❚` (duas
  barras encorpadas, dominavam a row) por `‖` em fonte 11px. O glifo
  fino combina melhor com a hierarquia visual do title/sub-row.

## [0.8.3] — 2026-05-18

### Adicionado
- **Runner — "Abrir browser ao carregar"**: novo checkbox no dialog de
  edição do runner. Quando ligado, a app observa a saída do `start_cmd`,
  detecta a URL (`http://localhost:3000`, `Listening on 8080`, etc.) e
  abre no browser do sistema uma vez por start. Campo "URL do browser"
  opcional permite forçar uma URL específica em vez de detectar.
- **Configurações → Browser**: campo global pra escolher o binário do
  browser (vazio = `xdg-open` / `QDesktopServices`). Aceita nome no
  PATH (`chromium`, `firefox`) ou caminho absoluto.
- **Aba do runner fica verde quando rodando** (vermelho em erro,
  default quando parado/idle/exited).

## [0.8.2] — 2026-05-18

### Alterado
- Prompt de "Gerar com Claude" para runners agora instrui o Claude a
  **inspecionar arquivos de referência** antes de decidir os comandos
  (`package.json`, `pom.xml`, `build.gradle`, `pyproject.toml`,
  `Cargo.toml`, `go.mod`, `Makefile`, `.nvmrc`, etc.). Evita chute em
  `npm run dev` quando o script não existe, e ajuda a casar versões de
  runtime (Java/Node) com a pasta correta.
- Prompt reescrito em 5 passos (listar raiz → ler manifests → **verificar
  toolchain instalado** (`node -v`, `java -version`, `dotnet --version`,
  app servers em `/opt/*`) → extrair comando real → derivar cwd/stop/
  restart), com regras específicas por stack (Node detecta pnpm/yarn/
  bun/npm pelo lockfile; Maven identifica spring-boot/tomcat7/jetty/
  cargo plugin; Python diferencia Django/FastAPI/Flask; Go/Rust/Ruby/
  PHP/.NET/Docker). Se a ferramenta não estiver instalada, runner é
  gerado com `enabled: false` e sufixo `(faltando: <tool>)`. Pede ao
  Claude reportar quais arquivos leu e o que extraiu, pra ficar auditável.

## [0.8.1] — 2026-05-18

### Adicionado
- Botão **↻ Recarregar runners** no header da aba Runners. O prompt
  do "Gerar com Claude" agora instrui o Claude a salvar o JSON em
  `~/.config/claude-workspaces/runner-drafts/<workspace-id>.json`,
  e o botão importa esse rascunho (merge por nome).

### Mudado
- **Gerar runner com Claude**: agora abre uma aba no terminal interno
  (xterm.js embutido) do workspace atual em vez de spawnar um konsole
  externo. O cwd continua sendo o repositório do claude-workspaces pra
  o Claude conseguir ler `docs/runners-spec.md`.

### Corrigido
- Clicar em um terminal no sidebar enquanto a aba **Runners** estava
  ativa não trocava pra aba **Terminal** — agora alterna corretamente
  e foca o terminal selecionado.

## [0.8.0] — 2026-05-18

### Adicionado
- **Runners**: cada workspace pode definir um conjunto de runners
  (processos de longa duração — web, api, glassfish, camera, mobile, …)
  com comandos `start`/`stop`/`restart` independentes. Nova aba **Runners**
  ao lado da aba Terminal mostra o log ao vivo de cada runner via PTY +
  xterm.js (mesmo motor da aba Terminal). Botões de **Rodar todos** /
  **Parar todos**, **Importar** / **Exportar** JSON, e **+ Novo runner**
  com opção "Gerar com Claude" — esta abre o Claude no diretório do
  próprio claude-workspaces (com `docs/runners-spec.md` carregado) pra
  gerar a config consumindo menos tokens. Persistência junto do workspace
  em `~/.config/claude-workspaces/workspaces.json`.

## [0.7.20] — 2026-05-18

### Removido
- **Sidebar — item "última sessão" por workspace**: removido o child que
  exibia a sessão mais recente do Claude embaixo de cada workspace na
  sidebar. Como as sessões abertas anteriormente já são restauradas
  automaticamente como abas, esse atalho ficou redundante. `Ctrl+Shift+R`
  continua retomando a última sessão do workspace atual.

## [0.7.19] — 2026-05-18

### Adicionado
- **Git panel — "Ver diff" no menu de contexto**: clicar com botão direito num
  arquivo modificado agora oferece a opção `👁 Ver diff`, que abre o painel de
  diff (se estiver oculto) e carrega o diff do arquivo clicado. Atalho útil
  pra evitar o passo manual de abrir o painel pelo botão da toolbar antes de
  selecionar o arquivo. Só aparece pra arquivos rastreados — untracked não
  tem diff.

## [0.7.18] — 2026-05-18

### Mudado
- **Sidebar de workspaces — visual menos poluído**: o nome do workspace
  aparece primeiro, seguido da bolinha verde e do badge `×N` (antes vinham
  antes do nome, brigando com a leitura). Fonte do nome um pouco maior
  (+1.5pt) e cor mais clara (`#f2f2f2`, quase branco) pra dar mais peso
  visual à informação principal.

## [0.7.17] — 2026-05-18

### Corrigido
- **Menu de contexto do git não abria**: os `QAction` criados em `_action()`
  não tinham parent — o Python coletava antes do `QMenu.exec_()` rodar, então
  o menu ficava só com os separadores e o Qt nem chegava a mostrá-lo. Agora
  parenta no `GitPanel`. Quebrou em 0.7.15 quando o menu de contexto ganhou
  esse helper. (Diagnosticado via log em `/tmp/claude-workspaces-debug.log`,
  já removido.)

## [0.7.16] — 2026-05-18

### Corrigido
- **Right-click no painel git**: agora usa o item clicado (e não a seleção
  antiga) quando se clica com botão direito em um arquivo não-selecionado.
  Antes, se o usuário tinha um repo/grupo selecionado e clicava com botão
  direito num arquivo, o menu mostrava as ações do repo/grupo — sem `Add` ou
  `Delete`.

## [0.7.15] — 2026-05-18

### Alterado
- **Menu de contexto do git**: rótulos simplificados pra `Add` e `Delete`
  (antes: `Add (stage)` e `Deletar arquivo`). Ícones (`+`, `✕`) mantidos.

## [0.7.14] — 2026-05-18

### Corrigido
- **Recalibração do limite 5h (de novo)**: `plan_usd_limit_5h` 375 → 700
  com base em terceiro ponto real (claude.ai 8% com sidebar marcando 15%
  → ratio 15/8 → $700). O quota interno da Anthropic parece pesar input
  diferente de output, então o ratio drifta com o mix de mensagens da
  sessão; calibrar via `settings.json` quando divergir.

## [0.7.13] — 2026-05-18

### Corrigido
- **Recalibração do limite 5h**: `plan_usd_limit_5h` 420 → 375 com base em
  segundo ponto real (claude.ai 7% com `cost_usd` $26.24 → $375). Sidebar
  agora bate mais perto do número do claude.ai. Ajuste fino via
  `settings.json` se a divergência voltar.

## [0.7.12] — 2026-05-18

### Adicionado
- **Limites semanais na sidebar** (replica `Weekly limits` do claude.ai):
  o bloco acima do "Novo Workspace" agora tem 3 linhas:
  `Sessão 5h: X% · reset Hh MMm` / `Semana (todos): X% · reset seg HH:MM`
  / `Semana (Sonnet): X%`. Reset semanal calculado como próxima segunda
  07:00 local. Limites configuráveis via `plan_weekly_usd_limit_all` e
  `plan_weekly_usd_limit_sonnet` em settings.json (defaults calibrados
  num ponto real: claude.ai 2% all-models com `cost_usd` semanal de
  $4730 → 100% ≈ $236k).
- Função `weekly_plan_usage(window_days=7)` em `usage_telemetry.py`
  separando custo total e custo só de Sonnet.

### Alterado
- **Removido `$X/$Y` do display** do uso 5h. Max 5x é assinatura, não
  pay-per-use; o cifrão era ruído. Valores absolutos permanecem no
  tooltip.

## [0.7.11] — 2026-05-18

### Corrigido
- **Sessão 5h: % e reset agora batem com claude.ai**: na 0.7.10 o
  `first_ts` era a mensagem mais antiga numa janela rolante de 5h —
  como a janela é fixa em "agora - 5h", o reset sempre dava ~0m e o
  cost somava várias sessões consecutivas (o exemplo do usuário marcou
  `128% · reset 0m` enquanto claude.ai mostrava `4% · resets in 4h 35m`).
  Agora `recent_plan_usage` detecta o início real da sessão atual
  (varre mensagens em ordem temporal e abre uma nova sessão sempre
  que aparece um gap ≥5h), soma apenas dessa sessão em diante, e o
  tooltip mostra a hora local do reset (`Reseta às 18:39 (4h43m)`).
- **Calibração do `plan_usd_limit_5h`**: default ajustado de
  `$200` → `$420` baseado em ponto real (claude.ai 4% com nosso
  `cost_usd` em $16.91 → 100% ≈ $420 num plano Max 5x). Continua
  configurável via `settings.json`.

## [0.7.10] — 2026-05-18

### Corrigido
- **Label acima do "Novo Workspace" agora mostra uso do plano (5h)**:
  na 0.7.8 o `Contexto: 45%` exibia o tamanho da janela de contexto da
  última mensagem assistant — métrica distinta do que claude.ai mostra
  em `Plan usage limits → Current session`. Substituído por
  `Sessão 5h: 99% · $198/$200 · reset 2h07m`, agregando o `cost_usd`
  de **todas** as sessões JSONL nos últimos 5h e dividindo pelo limite
  configurado em `plan_usd_limit_5h` (settings).

### Adicionado
- **% de contexto por sessão na linha do console**: cada row de console
  na sidebar agora mostra `opus-4-7 · 38% ctx · 75K in · 200K out · 8M
  cache`. O `38% ctx` é o tamanho da janela de contexto da última
  mensagem assistant relativo ao limite do modelo (200K, ou 1M se
  `[1m]`), com cor (verde <50% / âmbar 50-80% / vermelho ≥80%). Tooltip
  expande pra valores absolutos.
- **Setting `plan_usd_limit_5h`** (default `200.0` USD ≈ Max 5x) que
  controla o denominador do % global. Anthropic não publica o limite
  exato em tokens/USD; ajustar manualmente caso o número não bata com
  o que claude.ai mostra.

## [0.7.9] — 2026-05-18

### Alterado
- **▶ Continuar agora aparece só quando faz sentido**: o botão só fica
  visível em sessões restauradas no startup (`--resume` após reabrir o
  app) e que estão em estado **Ocioso** — cenário típico em que o
  Claude voltou parado no prompt no meio de uma tarefa. Em sessão
  fresca, trabalhando, aguardando ou já encerrada, o botão some.
  Encerrar permanece sempre visível na toolbar principal. Aplica-se
  aos dois locais (toolbar do console central e linhas da sidebar).
- **Botões ▶ ⚙ da sidebar alinhados à direita**, na mesma faixa da
  branch — antes ficavam grudados no título e pareciam pertencer à
  primeira linha. Agora estão centralizados verticalmente, junto da
  info de repo, separando "estado da sessão" (esquerda) de "controles
  + repo" (direita).

## [0.7.8] — 2026-05-18

### Adicionado
- **% de contexto da sessão ativa na sidebar**: novo label logo acima do
  botão `＋ Novo Workspace` mostra `Contexto: 45% · 90K/200K · opus-4-7`
  derivado da última mensagem assistant da sessão claimed do terminal
  em foco. Cor do % muda conforme uso: verde <50%, âmbar 50-80%, vermelho
  ≥80%. Limite usa 1M quando o modelo tem sufixo `[1m]`, 200K caso
  contrário. Some quando não há sessão ativa. Atualiza no mesmo poll de
  5s do git e imediato ao trocar de workspace/aba.

## [0.7.7] — 2026-05-18

### Adicionado
- **Modelo + tokens da sessão na sidebar**: 3a linha de cada row de
  console mostra `opus-4-7 · 139 in · 61.2K out · 8.5M cache` direto,
  sem precisar abrir o menu de contexto. Custo de propósito não vai
  nessa linha (continua no menu de contexto, evita poluir a sidebar
  com valor em USD). Tooltip expande pra valores absolutos. Atualiza
  junto do poll de git (a cada 5s).
- **Ações inline em cada console da sidebar**: `▶ Continuar` (manda
  'continue' direto) e `⚙ Modo` (abre o popup com Plan/Auto/Default,
  `/effort` e `/model`) à direita do título de cada row de console. O
  popup foi mantido porque permite escolher o modo antes de mandar —
  versão com botão `↹ Ciclar` direto perdia esse passo.
- **Toggle no header `WORKSPACES`** (botão `⌃`/`⌄` à direita do título
  da seção) que oculta/mostra esses botões em todos os consoles de uma
  vez. Estado persistido em `show_terminal_actions`. Menu de contexto
  (clique direito no console) continua exibindo as mesmas ações com a
  toolbar oculta.

### Corrigido
- **Branch + arquivos modificados (0.7.6) não aparecia** na sidebar:
  o `_repo_poller.request(term.claude_cwd)` mandava o método em vez
  do valor (`claude_cwd` é função, não property). Erro silencioso
  porque o TypeError caía no `except Exception` do worker. Agora
  chama com `()`.

### Alterado
- Revertido o toolbar expandido do console central (0.7.5) — volta pra
  `▶ Continuar / ⚙ Modo / Encerrar` original. As ações de ciclar modo /
  trocar effort / trocar modelo continuam atrás do popup `⚙ Modo`.
- Removido o toggle global de ações da TopBar (0.7.5); agora vive no
  header `WORKSPACES` da sidebar, junto da lista de consoles que ele
  controla.

## [0.7.6] — 2026-05-18

### Adicionado
- **Branch + arquivos modificados na sidebar**: cada console agora mostra
  no canto direito a branch atual (`⎇ nome`) e um contador `●N` em amber
  quando há arquivos modificados/staged/untracked no repo do workspace.
  Atualiza a cada 5s em segundo plano via `RepoStatusPoller` (QThreadPool
  + cache TTL de 4s), então não trava a UI mesmo em repos lentos. Tooltip
  no label expande pra texto completo (`Branch: foo — N arquivo(s)
  modificado(s)`).

## [0.7.5] — 2026-05-18

### Adicionado
- **Toolbar de ações em todo terminal**: os atalhos que antes só
  apareciam no menu de contexto da sidebar (Continuar / Ciclar modo /
  Trocar effort / Trocar modelo) agora ficam visíveis como botões no
  topo de cada console Claude. Substitui o antigo botão único `⚙ Modo`
  que abria um popup — clique direto faz a ação sem intermediário.
- **Toggle global "⌃ Ações"** na top bar (logo após "Claude Workspaces")
  pra ocultar/mostrar essa toolbar em todos os terminais de uma vez. O
  estado é persistido em `show_terminal_actions` nas settings. Mesmo com
  a toolbar oculta, as ações continuam acessíveis pelo menu de contexto
  da sidebar (clique direito no item do console).
- **Botões inline em cada workspace na sidebar**: ＋ (abre um Claude
  novo no workspace, mesma ação de "Abrir Claude") e ▾/▸ (recolhe ou
  expande os filhos do workspace na tree). O ícone do botão de
  colapsar sincroniza com o disclosure triangle nativo da árvore.
- **Indicador visual de "rodando" na sidebar**: substitui o texto
  `●×2` (que renderizava na mesma cor do nome do workspace e parecia
  bullet point) por uma bolinha verde dedicada + badge `×N` em pill
  verde-translúcida quando há mais de um Claude rodando no workspace.

## [0.7.4] — 2026-05-18

### Adicionado
- **Textos das notificações configuráveis** em Configurações → Notificações.
  Antes os títulos vinham fixos (`✅ Pronto`, `🔁 Ainda aguardando`,
  `Claude Workspaces` como app_name, `Claude — {project}` no hook Stop),
  o que deixava banners genéricos no centro de notificações — um popup
  só com "Claude Code" no topo não dizia qual workspace tinha terminado.
  Cinco campos novos:
  - **Nome do app**: usado no app_name do D-Bus, tooltip do tray e flag
    `-a` do `notify-send` do hook. Aparece como cabeçalho do popup.
  - **Prefixo 'pronto'** / **Prefixo re-lembrete**: vão antes do nome do
    workspace nos toasts emitidos pelo app. String vazia esconde o
    prefixo.
  - **Título do hook** (template, aceita `{project}`) e **body padrão
    do hook**: usados pelo `notify-hook.py` quando o Stop event dispara.
    Como o hook roda como subprocess separado do Claude Code, ele relê
    as settings de `~/.config/claude-workspaces/settings.json` a cada
    turno.
  Salvar Configurações recria o `DesktopNotifier` no ato pra que o
  `app_name` novo já valha pra próxima notificação (não dá pra mudar
  esse campo num notifier vivo via D-Bus).

## [0.7.3] — 2026-05-18

### Corrigido
- **Crash ao terminal mudar de estado running** (`AttributeError:
  'QTreeWidget' object has no attribute 'count'`): `_refresh_item_label`
  e `_search_submit` ainda usavam a API antiga de `QListWidget`
  (`count()`, `item(i)`, `setCurrentRow()`) depois da migração da
  sidebar pra `QTreeWidget`. Agora reusam `_find_workspace_item` e
  `topLevelItem(...)` corretamente, evitando a exceção a cada
  notificação de `running/idle` vinda do PTY.

## [0.7.2] — 2026-05-18

### Corrigido
- **Flicker de "Ocioso" durante o turno do Claude**: o parser de
  `claude_activity` oscila entre `is_working=True/False` enquanto o
  Claude alterna entre tool calls e geração de texto, fazendo o status
  na sidebar piscar "Trabalhando ↔ Ocioso". Agora a transição
  working→idle é debounced — só vira "Ocioso" se ficar N segundos
  estável sem voltar a working. Working→awaiting (`needs_decision`)
  continua imediato, pra não atrasar o feedback de permission prompts.

### Adicionado
- **Setting global `idle_debounce_seconds`** (default **20s**, range
  0–120s) na seção "Detecção de status" da tela de Configurações.
  Controla o debounce acima. Aplicado a todos os terminais vivos
  imediatamente após salvar (via class-attr em `TerminalWidget`,
  sem precisar reiniciar). 0 desliga o debounce (volta ao
  comportamento antigo, com flicker).
- **Janela de graça pós-startup (3s)** no `TerminalWidget`: nos
  primeiros 3 segundos depois do PTY entrar em running, o debounce
  working→idle é ignorado. Fecha o caso "reabri o app com sessões
  já no prompt principal e fiquei 20s vendo 'Trabalhando' até virar
  'Ocioso'" — agora vira "Ocioso" assim que o parser confirma o
  marker idle, sem esperar o debounce.

## [0.7.0] — 2026-05-18

### Adicionado
- **Botão "⚙ Modo"** na toolbar de cada terminal Claude, ao lado de
  ▶ Continuar / Encerrar. Abre um popup estilo VS Code com:
  - Os 5 modos do Claude Code (Ask before edits / Edit automatically /
    Plan / Auto / Bypass permissions) descritos um por um. Clique em
    qualquer linha = manda `Shift+Tab` no PTY (cicla pro próximo modo).
  - "Trocar effort" — abre `/effort` no prompt.
  - "Trocar modelo" — abre `/model` no prompt.
- **Infos da sessão no menu de contexto da sidebar**: clique direito num
  console mostra modelo da última mensagem assistant, total de tokens
  (in/out/cache) e custo aproximado em USD — lidos do JSONL claimed em
  `~/.claude/projects/`. Embaixo das infos, mesmos atalhos do popup:
  Continuar / Ciclar modo / Trocar effort / Trocar modelo.
- **Probe de versão do Claude Code no startup** (`claude_probe.py`):
  roda `claude --version`, parseia e loga se está fora do range testado
  (`TESTED_CLAUDE_RANGE` — hoje `2.1.0`–`2.1.999`). Não bloqueia. Útil
  pra explicar regressões depois de auto-updates do Claude Code que
  mudem schema dos JSONLs, copy do TUI ou slash commands.

### Mudado
- `usage_telemetry.UsageStats` ganhou campo `last_model` — reflete o
  modelo da última mensagem assistant (acompanha `/model` mid-session).
- `usage_telemetry.usage_for_session(jsonl_path)` novo helper —
  agrega tokens/custo de **uma** sessão sem varrer todos os projetos.
- `TerminalWidget.claimed_session_path()` exposto pro menu de contexto
  conseguir ler o JSONL da sessão claimed.

## [0.6.0] — 2026-05-18

### Adicionado
- **Favoritar sessão (★)** no card de cada sessão recente: clique na estrela
  marca/desmarca a sessão como favorita. Persiste em
  `~/.config/claude-workspaces/session_marks.json` (não mexe nos arquivos do
  Claude Code em `~/.claude/projects/`).
- **Filtro "só favoritas"** no header de Sessões recentes (botão ★ ao lado do
  campo de busca). Combina com o filtro de texto.
- Sessões favoritadas são **sempre carregadas**, mesmo que estejam fora das 20
  mais recentes — fecha o caso "marquei pra achar depois e a sessão envelheceu".
- Novo módulo `session_marks` com API `is_starred / set_starred / starred_ids`.
  A estrutura do JSON já reserva campos `tags` e `note` pra evolução futura
  (tags nomeadas, anotações livres) sem precisar migrar formato.

### Corrigido
- Filtro de texto da lista de Sessões recentes estava parcialmente quebrado:
  o `QListWidgetItem` não armazenava o `ClaudeSession` em `UserRole`, então
  digitar qualquer coisa escondia todos os cards em vez de buscar pelo preview.
  Agora o `UserRole` é populado e a busca por texto realmente filtra.

## [0.5.1] — 2026-05-18

### Adicionado
- Botão **"▶ Continuar"** na toolbar de cada terminal: manda `continue` + Enter
  pro Claude com um clique. Resolve o caso de reabrir o app com várias sessões
  retomadas e ter que digitar manualmente em cada uma pra elas voltarem a
  trabalhar.
- **Menu de contexto na sidebar** (botão direito) com:
  - "▶ Continuar este console" em cima de uma aba de terminal Claude.
  - "▶ Continuar todos os consoles deste workspace" em cima do nome do workspace
    — manda `continue` em rajada pra todos os consoles vivos daquele workspace.
- Botão **"esconder tudo"** (▸) no topo do strip do dock direito: fecha todos
  os painéis abertos de uma vez (Git/Memória/Skills). Quando todos fechados,
  o strip continua visível com os ícones pra reabrir.

### Mudado
- **Activity bar** (à esquerda) reestilizada: glyphs Unicode monocromáticos
  (❒/☰/⚓/⌬/◆/▣/⚙) no lugar dos emojis coloridos; presentation selector
  U+FE0E + font-stack `Symbola/DejaVu`/etc forçam renderização de "ícone
  técnico" em vez de "emoji infantil". Hover/checked migrados pra paleta
  do `theme.*`.
- **Dock direito** com botões de painel mais limpos: ícones glyph (⎇ Git,
  ❏ Memória, ✦ Skills) com tooltip no lugar do texto rotacionado, paleta
  unificada via `theme.*`, strip um pouco mais largo (32→36px) pra acomodar
  os glyphs com folga.
- `DockPanelSpec` ganhou campo `icon` opcional pra o glyph exibido no strip.

## [0.5.0] — 2026-05-18

### Adicionado
- Exibição da versão atual na sidebar, logo abaixo do botão "🔧 Hack este app".
- Diálogo de release notes ao clicar na versão: mostra o que mudou na versão atual
  e o histórico completo de versões anteriores (parseado deste `CHANGELOG.md`).
- Subsistema de **plugins** completo: spec v1.0, loader, validador, registry, runtime
  Python com `ctx.workspaces`/`ctx.sessions`/`ctx.fs`/`ctx.http`, 6 eventos com timeout,
  paleta de comandos (Ctrl+P), view top-level Plugins (🧩 Ctrl+5), tela de detalhe
  em PT-BR, configurações inline com auto-save, botão "Exemplos" instalando bundles
  do repo, botão pra solicitar criação de novo plugin via Claude, card amigável de
  onboarding e 4 exemplos prontos (commit-coach, idle-rescue, focus-timer,
  workspace-snapshot).
- View **Apps** (🧰 Ctrl+Shift+6) com PWAs embutidos via QtWebEngine.
- Notificações nativas via D-Bus com botões de ação (Abrir/Adiar/Já vi), tray nativo,
  re-lembretes da inbox e claim de sessão por aba.
- Restaurar abas Claude ativas ao reabrir o app.
- Detecção de PR existente: abre direto no navegador com busy state, ou cria um novo
  via `gh` CLI a partir do painel Git.
- Estado **"Aguardando"** na sidebar (decisão pendente), separado de **"Ocioso"**
  (no prompt). Detecta também pickers interativos ("Enter to select…").
- Handoff entre consoles com briefing rico e prompt-ready, detectando Claude antes
  de colar.

### Mudado
- Painel de detalhe dos plugins agora rola em vez de comprimir conteúdo.
- Sidebar foca aba ativa com clique simples (em vez de duplo).
- Card de sessão mais compacto.
- Paleta de comandos dos plugins migrou de `Ctrl+P` pra `Ctrl+Shift+P` (convenção
  VS Code; `Ctrl+P` volta a abrir Quick Open de arquivo).
- Tooltips do activity bar corrigidos pra refletir `Ctrl+Shift+1..6`.
- Documentação (README/USAGE/DEVELOPMENT) atualizada cobrindo plugins, apps, notif
  nativas e session restore.
- **Sidebar de workspaces** repaginada: cabeçalho "WORKSPACES" com caps/letter-spacing
  e borda inferior sutil; seleção mais suave (tint azul + borda lateral em vez de
  bloco saturado); hover discreto; nomes de workspace em negrito pra hierarquia
  clara; linha "↻ última sessão" em itálico/menor/muted; botão "+ Novo Workspace"
  reestilizado como ação primária neutra; "🔧 Hack este app" agora é ação ghost.
- Linhas de console na sidebar mais compactas (48px → 42px) com estado e última
  ação na mesma sublinha separadas por ponto, paleta unificada via `theme.*`.

### Corrigido
- Consoles vivos somem da sidebar quando workspace tem child "↻ histórica".
- Título de sidebar desambiguado quando dois Claudes começam com o mesmo prompt.
- Actions clicadas pela central do Plasma 6 não disparavam callback.
- Banners "✅ Pronto" espúrios durante extended thinking / tool runs lentas
  (working↔idle flipping no parser de atividade).
- Notificações D-Bus empilhando ao receber re-lembrete + banner stale após o
  Claude voltar a trabalhar (usa `replaces_id` e fecha proativamente quando o
  tab sai da inbox).
- Atalho `Ctrl+P` estava bound duas vezes — abria a paleta de plugins em vez
  do Quick Open de arquivo.
- Limpa botões fantasmas ao trocar de plugin selecionado.
- Ignora `__pycache__` silenciosamente na validação do bundle de plugins.

## [0.4.0] — 2026-02-12

### Adicionado
- **Activity bar** vertical à esquerda + views top-level pra Catálogo, Hooks, MCP
  e Settings (Ctrl+Shift+1..6).
- Catálogo navegável de skills/agents/commands.
- Inspectores visuais de hooks e MCP, com editor e playground.

### Mudado
- Refactor `PR1`: 4 coordinators extraídos do `MainWindow`.
- Refactor `PR2`: `errors.py` + logs nos `except` críticos.
- Refactor `PR3`: zero `subprocess` direto na camada UI.
- Esconde tarefas concluídas da sidebar (mantém em sessões recentes).

### Corrigido
- Terminal maximiza/aumenta mesmo com Settings aberto.
- Minimizar terminal mantém barra do título visível.
- Detecção positiva de "working" evita "Trabalhando" grudado.
- Resize pós-fork pra Claude usar largura total do terminal.

## [0.3.0] — 2025-12-02

### Adicionado
- **Telemetria de skills** (uso e último-lido das sessões do Claude).
- **Busca full-text** nas sessões (Ctrl+Shift+F).
- **Telemetria de uso/custo** — tokens e $ estimado inline.
- **Templates de workspace** — bundled + custom JSONs.
- Overrides per-workspace pros defaults de git/worktree.
- "Criar nova branch" habilitada sem worktree (git checkout -b in-place).
- Auto-resume da última sessão (Ctrl+Shift+R) + export markdown da sessão.

### Mudado
- `DockPanel` Protocol + `DOCK_PANEL_SPECS` (manutenibilidade #3).
- `TerminalState` concentra os 4 dicts soltos (manutenibilidade #5).
- `services/launch_planner` extraído (manutenibilidade #4).
- Testes pra 7 módulos puros + ruff no CI.

### Corrigido
- "Criar nova branch" ficava trancado + `right_splitter` sem snap.

## [0.2.0] — 2025-10-15

### Adicionado
- **Painel Git** como terceira coluna — branch, status, double-click abre no editor.
- Diff inline + ações git (checkpoint estilo IntelliJ).
- Context menu do Git (Add upfront, Stage/Unstage/Rollback/Delete).
- **Dock direito** estilo IntelliJ — tool strip vertical com botões rotacionados.
- Sidebar `QTreeWidget` — workspaces com children mostrando consoles ativos.
- Filtros Skills/Agents/Comandos + child widget rico + filtro de sessões em tempo real.
- Inbox global de consoles aguardando atenção — bell no topbar.
- Painel **Memória** — editor do `CLAUDE.md` da pasta primária no dock.
- Worktree opcional ao abrir Claude — checkbox no `LaunchClaudeDialog`.
- Tree mostra título da sessão Claude (1º prompt), tooltip com texto completo.
- Checkbox de pastas + criar/usar branch existente no launch dialog.
- Handoff entre consoles + configs gerais de worktree.

### Mudado
- App-wide dark palette + Fusion style (Breeze do KDE ignorava QSS).
- `theme.py` centraliza paleta + helpers.
- Resize com debounce do refit + queue cancel no JS.

### Corrigido
- `launch_paths` nunca colapsa pro pai comum.
- Double-click no tree de sessão abria Konsole externo.
- Parser de atividade ignora footer + ANSI strip mais robusto.

## [0.1.0] — 2025-08-20

### Adicionado
- Esqueleto inicial em PySide6.
- Sidebar de workspaces, launchers de IDE, aba de Settings e botão de self-dev
  ("🔧 Hack este app").
- Logging, instalador `.desktop` e manuais de uso/dev.
- **Terminal embutido** com xterm.js + pty no painel direito.
- Abas de terminal por workspace + retomar sessões do Claude.
- Notificações via hook `Stop` do Claude + sessões multi-folder.
- Badge de workspace rodando + busca na sidebar.
- Refactor de layout — topbar global, terminal full-width, tarefas e cards.
- AUR `PKGBUILD` + correções UX no layout.
- Sessão→tarefa, atalhos de workspace, drag-drop de pastas, estado da aba.
- Busca por tarefas + Enter pra primeiro match + testes + CI.
- Terminal confinado ao painel direito + botões maximizar/minimizar.
- Filtros Pendentes/Concluídas/Todas no painel de Tarefas.
- Gerenciar MCP postgres por workspace + fix init dos chips.

### Corrigido
- Usar shell de login (`/etc/passwd`) em vez de `$SHELL` pra resolver aliases.
- Enviar bytes crus do pty como `QByteArray` pra preservar UTF-8.
- Usar pai comum como cwd quando todas as pastas são irmãs.
- Cores explícitas na lista de tarefas (texto invisível em tema dark).
