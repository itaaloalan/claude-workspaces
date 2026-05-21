# Changelog

Todas as mudanças relevantes neste projeto são documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto segue [versionamento semântico](https://semver.org/lang/pt-BR/) pragmático
(pré-1.0: `minor` para features visíveis, `patch` para correções/refactors).

## [0.54.4] — 2026-05-21

### Corrigido
- **Supressão de notificação do console em foco agora funciona de fato**
  (`ui/main_window.py` — `_on_inbox_alert`): a 0.54.2 comparava
  `id(terminal_host.currentWidget())` com `tab_id`, mas
  `terminal_host.currentWidget()` retorna a `TerminalArea` do workspace
  (uma por workspace), não o `TerminalChildWidget` (um por console) —
  então o `id()` nunca batia e a supressão nunca disparava. Agora desce
  até `area.tabs.currentWidget()`, que é o widget cujo `id()` é o
  `tab_id` emitido pelo `terminal_coordinator`.

## [0.54.3] — 2026-05-21

### Corrigido
- **Botões da title bar dos docks invisíveis/clicáveis sem efeito**
  (`ui/dock_manager.py`): os ícones default do QtAds são pretos
  sem alpha e somem no tema dark. Agora `_install_dark_icons` registra
  glyphs unicode claros (✕ ⋮ ⧉ — 📌) via `CIconProvider.registerCustomIcon`
  pros 6 tipos de ícone (TabClose, DockAreaClose, Menu, Undock,
  Minimize, AutoHide).
- Removido `qproperty-iconSize: 12px 12px` que restringia o hit area
  dos botões; usa `min-width/min-height: 18px` em vez.
- Placeholder do input "Buscar workspaces" usa palette explícita pra
  ficar visível em fundo escuro (antes ficava quase imperceptível).

## [0.54.2] — 2026-05-21

### Corrigido
- **Notificação suprimida quando o console alertante já está em foco**
  (`ui/main_window.py` — `_on_inbox_alert`): se a `MainWindow` está
  ativa, não-minimizada, e o tab visível no `terminal_host` é
  exatamente o que disparou o alerta, o evento é descartado antes do
  toast/D-Bus/tray. Reminders também ficam silenciados nesse caso. Se
  o usuário troca de tab, vai pra outra janela ou minimiza, o
  comportamento normal de notificação volta.

### Por quê
Ficar avisando "Pronto" pra um console que o próprio usuário já tá
olhando é puro ruído visual — ele acabou de ver o prompt aparecer.

## [0.54.1] — 2026-05-21

### Corrigido
- **Sidebar duplicada e centro vazio** (`ui/main_window.py`): a ordem
  de criação dos `CDockWidget`s estava errada — left antes de center
  faz o QtAds criar um segundo dock area no lado esquerdo em vez de
  ancorar ao centro. Agora cria center primeiro, depois left/right.
- **Schema do `body_dock_state` bumpado pra 1** (`settings.py`): states
  salvos pelas 0.52/0.53 (layout quebrado) são descartados na primeira
  abertura da 0.54.1. Layout volta ao default e re-persiste correto.
- **Gradiente branco nas title bars dos docks** (`ui/dock_manager.py`):
  aplica QSS dark ao QtAds (tab bar, area title bar, splitter handle,
  floating container) alinhado com o tema do app.

## [0.54.0] — 2026-05-21

### Mudado
- **Confirmações de ação viraram toast slim** em vez de
  `QMessageBox.information` modal centralizado
  (`ui/persistent_toast.py` — novo `FlashToast`/`flash_toast`):
  "Configurações salvas" (`ui/settings_panel.py`), "Salvo" do skill
  editor (`ui/skill_editor_dialog.py`), "Instalado" da skill
  (`ui/skill_detail_view.py`, `ui/skill_detail_dialog.py`) e
  "Rascunho importado / Cópia concluída / Importação concluída"
  do runner area (`ui/runner_area.py`). O toast aparece no canto
  inferior-direito da tela do cursor, não rouba foco, e some sozinho
  em ~2.5s.

### Por quê
O modal "Pronto, configurações atualizadas." aparecia no centro da
tela e bloqueava a janela — era a queixa principal: poluído, no
centro, modal. Confirmações de sucesso não precisam de clique do
usuário. Erros (`QMessageBox.critical/.warning`) e diálogos que
mostram output útil (fetch/pull) continuam modais.

## [0.53.0] — 2026-05-21

### Adicionado
- **Seção "FIXADOS" na sidebar com pin/unpin** (`models.py`,
  `ui/coordinators/workspace_coordinator.py`, `ui/main_window.py`):
  campo `pinned: bool` no `Workspace` (default False, retrocompatível).
  Click direito num workspace mostra "📌 Fixar/Desafixar workspace".
  Fixados saem da lista principal e vão pra seção "FIXADOS" no topo.
- **Input de busca local de workspaces** na sidebar
  (`ui/builders/sidebar_builder.py`): filtra a lista por nome igual o
  search do top bar, mas colado na própria sidebar (estilo
  VSCode/JetBrains). Os dois inputs convergem pro mesmo `_apply_filter`.
- Header items não-selecionáveis dentro do tree (`_add_section_header`)
  pra delimitar "FIXADOS" e "WORKSPACES".

### Mudado
- `_visible_rows` e fallbacks de seleção pulam os header items.

### Fase 2a da remodelagem IDE-like
Sub-fase da Fase 2. Próximas: buckets (Arquivos / Sessões Claude N /
Runners N) e migração Model/View.

## [0.52.0] — 2026-05-21

### Adicionado
- **Sistema de docking IDE-like com PySide6-QtAds** (`ui/dock_manager.py`,
  `ui/main_window.py`): substitui o `body_splitter` externo (3 colunas:
  sidebar / centro+terminal / right_dock) por `CDockManager`. Cada coluna
  vira um `CDockWidget` que pode ser fechado, flutuado, auto-hide ou
  movido por drag-and-drop estilo VSCode/Qt Creator.
- Persistência de layout via `body_dock_state` (base64 do `saveState()`)
  no `settings.json`. `body_splitter_sizes` mantido como legado.

### Mudado
- `_toggle_sidebar` e `_toggle_right_dock` agora delegam pro
  `WorkspaceDockManager.toggle()` (hide/show do CDockWidget) em vez de
  manipular tamanhos de splitter na mão.
- Dependência nova: `PySide6-QtAds>=4.4`. PySide6 alinhado pra 6.11.0
  (versão suportada pelo binding).

### Fase 1 da remodelagem IDE-like
Primeira de 6 fases planejadas. As próximas vão substituir a sidebar
por `QTreeView` real, trazer cabeçalho com chips no centro, abas no
console, status bar permanente, ícones via qtawesome etc.

## [0.51.2] — 2026-05-20

### Mudado
- **Card do console mais compacto, ações sobem pra linha do título**
  (`ui/terminal_child_widget.py`): bloco de ações inline (✏ ▶ ⚙ ✖) saiu
  da row do estado e foi pra row do título, à direita. A linha do estado
  fica fininha, só com texto (sem `font-weight: 600` e sem competir com
  os botões por espaço vertical). Spacing entre rows zerado (`vbox`
  spacing 0, outer margins top/bottom 0) e altura do widget cai de 58 →
  52px (`_CHILD_HEIGHT` 66 → 60 no `main_window.py`). Chip do modelo
  perde o bold pra deixar o título como único elemento em peso 600 na
  row.

## [0.51.1] — 2026-05-20

### Mudado
- **Toast in-app só aparece com a MainWindow visível** (`ui/main_window.py`):
  `_show_persistent_toast` agora faz early-return quando a janela está
  oculta (tray) ou minimizada. Sem isso o overlay frameless caía
  centralizado em algum monitor mesmo com o app fora de foco, e a
  notificação do S.O. já cobre o aviso nesse cenário.
- **Toast arrastável** (`ui/persistent_toast.py`): usuário pode mover o
  toast clicando e arrastando. Depois de mover, `position_toasts` respeita
  a posição manual (flag `_dragged`) — não reempurra de volta pro canto e
  não conta a altura do toast arrastado na pilha dos outros.

## [0.51.0] — 2026-05-20

### Mudado
- **Item do console na sidebar mais compacto** (`ui/terminal_child_widget.py`,
  `ui/main_window.py`): fundida a linha da "última ação" (statusline) na
  mesma linha do estado — agora aparece como `Trabalhando · (disabled))`
  em vez de ocupar uma linha própria. Altura do card cai de 74→58px
  (`_CHILD_HEIGHT` de 82→66) e as margens verticais do outer layout
  passam de 2→1px. Mantém as 3 linhas essenciais: título / estado+ação /
  modelo+branch.

## [0.50.5] — 2026-05-20

### Corrigido
- **Toast in-app aparecia centralizado na tela em vez do canto top-right**
  (`ui/persistent_toast.py`, `ui/main_window.py`): no KWin Wayland o
  `Qt.Tool | FramelessWindowHint` cai na "smart placement" do compositor
  e o `setGeometry` pré-show é ignorado — toast nascia no centro. Trocado
  pra `Qt.SplashScreen` (window-type que o KWin não auto-posiciona) e
  somado um `position_toasts` via `QTimer.singleShot(0, …)` depois do
  `show()` no fluxo de criação, garantindo que o reposicionamento valha
  uma vez que o surface Wayland exista.

## [0.50.4] — 2026-05-20

### Mudado
- **`restart_all` do header da sidebar ignora flag `enabled`**
  (`ui/runner_area.py`): "Reiniciar todos" agora reinicia geral sem
  exceção — runners com `enabled: false` no JSON também sobem. O flag
  `enabled` continua valendo só pro "▶ Rodar todos" do painel de
  runners (escopo restrito por design).

## [0.50.3] — 2026-05-20

### Corrigido
- **Parar/Reiniciar todos do header da sidebar — `AttributeError: 'bool'`**
  (`ui/main_window.py`): o sinal `QPushButton.clicked` emite `checked: bool`
  posicionalmente, que sobrescrevia o `w=ws` das lambdas
  `on_stop_all`/`on_restart_all` e fazia `_get_or_create_runner_area(True)`
  estourar com `AttributeError: 'bool' object has no attribute 'id'`. A
  exceção era silenciosa do ponto de vista do usuário — clique sumia e os
  runners não startavam. Agora a assinatura é
  `lambda _c=False, w=ws, …: …` nos quatro pontos (workspace+console).

## [0.50.2] — 2026-05-20

### Corrigido
- **`restart_all` resyncs tabs e loga decisão por runner**
  (`ui/runner_area.py`): chama `_refresh_from_workspace()` antes de
  iterar pra cobrir o caso de o RunnerArea estar fora de fase com
  `ws.runners` (import/draft que não passaram por `_open_runner_edit`).
  Log INFO por runner com a decisão (start/restart/skip-disabled) pra
  facilitar debug em `~/.local/state/claude-workspaces/app.log`.

## [0.50.1] — 2026-05-20

### Corrigido
- **Reiniciar todos no header da sidebar agora starta runners parados**
  (`ui/runner_widget.py`): a guarda `_bridge_ready` no `_spawn` segurava
  o `start`/`restart` enquanto o QWebChannel da view não tivesse
  sinalizado `frontend_ready`. Quando o usuário clicava ↻ com o
  RunnerArea ainda não realizado (painel nunca aberto), o bridge demorava
  demais e o pending_cmd ficava na fila — processos nunca subiam.
  PTY agora roda independente do display; output pré-bridge fica só
  no `_log_buf` (já disponível via "Copiar log").

## [0.50.0] — 2026-05-20

### Adicionado
- **Botão ✏ inline pra renomear console na sidebar**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): o row de cada
  console ganhou um ícone de edit alinhado à direita ao lado de ▶ ⚙ ✖.
  Mesma ação do "Renomear sessão…" do clique direito — agora acessível
  em um clique sem precisar abrir o menu de contexto.

## [0.49.0] — 2026-05-20

### Adicionado
- **Parar todos / Reiniciar todos no header da sidebar**
  (`ui/runner_group_widget.py`, `ui/runner_area.py`,
  `ui/main_window.py`): o cabeçalho "Runners workspace" / "Runners
  console" ganhou dois botões compactos — `■` para parar tudo do
  escopo e `↻` para reiniciar tudo (usa `restart_cmd` quando o runner
  define um, senão faz stop+start). `RunnerArea` expõe `run_all`,
  `stop_all` e `restart_all` públicos pra o header disparar sem
  precisar focar a aba de runners; o restart no escopo workspace
  instancia a área lazy se ainda não existia.

## [0.48.1] — 2026-05-20

### Corrigido
- **Sidebar não fica mais presa em "cooldown" do uso do plano**
  (`plan_usage_api.py`, `ui/main_window.py`): TTL do cache de
  `/api/oauth/usage` subiu de 5min pra 30min, e o clique no ⟳ agora
  respeita o `Retry-After` do servidor em vez de forçar uma nova
  chamada — antes, cada force durante o cooldown renovava a janela de
  429 e prolongava o bloqueio indefinidamente. A granularidade de
  30min é suficiente pros números do plano e evita conflito de
  rate-limit com o CLI oficial que compartilha o mesmo token.

## [0.48.0] — 2026-05-20

### Adicionado
- **Aba do terminal espelha o nome da sidebar**
  (`ui/terminal_area.py`): texto da aba do `QTabWidget` agora usa
  `effective_title()` do widget (mesma fonte que sidebar consulta) com
  prefixo `#N` baseado em ids ordenados (mais antigo = #1). Renomear
  uma sessão pela sidebar (`set_custom_name`) reflete na aba na hora
  porque o re-emit de `activity_changed` força `_emit_activity` a
  reescrever o texto. Fechar uma aba renumera os irmãos restantes.

## [0.47.1] — 2026-05-20

### Adicionado
- **Prefixo separado pra notificação de decisão**
  (`settings.py`, `ui/settings_panel.py`, `ui/main_window.py`,
  `ui/coordinators/terminal_coordinator.py`): novo
  `notify_decision_prefix` (default `"❓ Decisão"`) usado quando o
  Claude abre um picker/permission prompt. Antes esses casos
  apareciam como `"✅ Pronto"` mesmo que o Claude não tivesse
  terminado, só estivesse perguntando — agora o título reflete a
  semântica correta. Configurável em Settings → Notificações.

### Corrigido
- **Notificação "✅ Pronto" fantasma ao abrir um novo terminal**
  (`ui/coordinators/terminal_coordinator.py`): o parser do TUI do Claude
  caía no fallback `recent && !looks_prompt` durante o render do
  welcome banner (sem working/idle marker ainda detectado), flipava
  `is_working` pra True e, quando o output dava uma pausa, voltava pra
  False — esse working→idle fake disparava o alerta. Agora o
  coordinator só conta como working→idle real se o tab ficou em
  working por ≥ 1.5s. Turnos reais do Claude duram bem mais que isso;
  flickers de startup duram milissegundos.

## [0.47.0] — 2026-05-20

### Adicionado
- **Clicar no `host:port` do runner na sidebar abre a URL no
  navegador** (`ui/runner_child_widget.py`): label do endereço virou
  clicável (cursor de mão, hover sublinhado), reaproveitando
  `services.system_open.open_url`. Tooltip passou pra "Abrir … no
  navegador" e URL sem esquema ganha `http://` automaticamente.

## [0.46.1] — 2026-05-20

### Corrigido
- **Clicar na notificação não focava o terminal quando o painel
  inferior tava na aba "Runners workspace"/"Runners (console)"**
  (`ui/main_window.py:_focus_tab_from_inbox`): além de selecionar a
  sub-aba do console, agora também volta o `_bottom_tabs` pra aba
  "Terminal". Sem isso o `setCurrentIndex` da aba interna era
  invisível porque o painel mostrado era o de runners.

## [0.46.0] — 2026-05-20

### Alterado
- **Botões "Abrir Terminal", "Claude (sem contexto)" e "Hack este app"
  mudaram pra activity bar à esquerda** (`ui/activity_bar.py`,
  `ui/builders/sidebar_builder.py`, `ui/main_window.py`): viraram
  ícones acima de Settings, liberando ~120px de espaço vertical na
  sidebar de workspaces. Comportamento idêntico ao anterior — só a
  posição mudou.
- **"Abrir console" na notificação seleciona o console no sidebar e
  restaura o pane do terminal** (`ui/main_window.py`):
  `_focus_tab_from_inbox` agora marca o row filho do console (não só
  o workspace), expande o workspace se estava colapsado, rola pra
  visível, restaura o pane do terminal se estiver minimizado e traz
  a janela pra frente. Antes só trocava de aba — fácil de perder de
  vista qual console pediu atenção.

## [0.45.0] — 2026-05-20

### Adicionado
- **Renomear sessão do Claude — o nome aparece nas notificações**
  (`session_marks.py`, `ui/terminal_widget.py`, `ui/main_window.py`):
  novo item "✏ Renomear sessão…" no menu de contexto da sidebar.
  O nome custom tem precedência sobre o preview do primeiro user prompt
  no título do card e no body das notificações ("Pronto" / "Ainda
  aguardando"), então dá pra apelidar sessões longas/parecidas e bater
  o olho no toast já sabendo qual é. Persiste em
  `session_marks.json` por `session_id` — sobrevive a fechar/reabrir o
  app. Deixar o campo vazio remove o apelido e volta pro preview.

## [0.44.2] — 2026-05-20

### Corrigido
- **Toasts centralizados em vez de top-right**
  (`ui/persistent_toast.py`, `ui/main_window.py`): `position_toasts`
  rodava DEPOIS de `toast.show()` — KWin já tinha aplicado sua
  placement policy (centraliza tool-windows frameless) e ignorava
  o `move()` posterior. Trocado pra `setGeometry` (atomic
  size+position) chamado ANTES do `show()`. Bonus: top-down do
  canto top-right na tela do cursor, sem sobreposição.

### Melhorado
- **Auto-dismiss em 5s em vez de 30s**
  (`ui/persistent_toast.py`): duração default reduzida pra
  casar com expectativa de "toast" comum — aviso rápido com
  barra de progresso mostrando countdown. Hover continua
  pausando pra dar tempo de ler.

## [0.44.1] — 2026-05-20

### Corrigido
- **Toasts sobrepostos no canto da tela**
  (`ui/persistent_toast.py`, `ui/main_window.py`): `position_toasts`
  era chamado logo após `toast.show()`, antes do Qt processar o
  showEvent e calcular a geometria real — `sizeHint().height()`
  retornava valor stale e dois toasts seguidos terminavam com a
  mesma altura no cálculo, sobrepondo. Diferimos a chamada via
  `QTimer.singleShot(0, ...)` pro próximo tick do event loop, e
  passamos a usar `frameGeometry().height()` (real) com fallback
  pra sizeHint. Também: posicionamento na tela do cursor
  (multi-monitor) em vez de sempre na primária.

- **Notif do SO ficava sticky pra sempre**
  (`ui/main_window.py`): com a divisão de responsabilidades, a
  notif do sistema tinha virado `urgency=critical` pra ser
  sticky — mas isso é o toast in-app que carrega. Voltamos pra
  `urgency=normal` + timeout configurável (10s default): notif
  do SO some sozinha pra não acumular popup velho.

## [0.44.0] — 2026-05-20

### Adicionado
- **Toast in-app com botões "Já vi" e "Adiar 5min"**
  (`ui/persistent_toast.py`, `ui/main_window.py`): mesmo
  conjunto de ações do sininho do inbox (`dismiss_inbox` /
  `snooze_inbox`), agora acessíveis direto do toast no canto
  da tela. "Abrir console" continua como CTA principal à
  direita; secundários ficam à esquerda com peso visual menor.

### Corrigido
- **Notif "Pronto" duplicando várias vezes**
  (`ui/main_window.py`): console oscilando working↔idle
  rapidamente (Claude rodando hooks/sub-passos entre estados)
  disparava 5+ notificações "✅ Pronto" por turno. Adicionado
  debounce de 60s por tab_id — só a primeira transição
  working→idle de cada turno emite alerta; subsequentes
  dentro de 60s são suprimidas. Reminders escapam do
  debounce (rodam em timer próprio, são intencionais).
  Debounce é limpo quando o tab realmente sai do inbox.

## [0.43.1] — 2026-05-20

### Melhorado
- **Toast in-app: top-right, auto-dismiss com barra de progresso**
  (`ui/persistent_toast.py`): toast agora aparece no canto
  superior direito (estava bottom-right), some sozinho depois de
  30s (auto-dismiss) com uma barra de progresso de 3px no rodapé
  que encolhe mostrando o tempo restante. Hover pausa o timer —
  enquanto o mouse estiver em cima, o toast não some. Stacking
  ajustado pra top-down (mais antigo em cima, novos descem) com
  `adjustSize` antes de pegar altura, evitando sobreposição.

## [0.43.0] — 2026-05-20

### Adicionado
- **Toast in-app frameless top-most com botão "Abrir console"**
  (`ui/persistent_toast.py`, `ui/main_window.py`): nova
  estratégia de notificação que separa responsabilidades:
  notif do sistema (D-Bus) fica SEM action e SEM som (assim KDE
  Plasma deixa sticky sem fight de hints), e um toast in-app
  no canto bottom-right da tela carrega o botão de ação + toca
  o som de alerta. Lifecycle 100% nosso: aparece, fica visível
  até clicar Abrir/X ou o tab sair do inbox, empilha quando há
  múltiplos consoles em inbox. Usa `Qt.Tool |
  FramelessWindowHint | WindowStaysOnTopHint` pra ficar acima
  de outras apps sem roubar foco.

### Removido
- **Keepalive D-Bus e re-emit 200ms**
  (`ui/main_window.py`): com a notif do sistema agora sem
  action, KDE Plasma deixa sticky naturalmente — não precisa
  mais re-emitir a cada 5s nem forçar re-emit pra renderizar
  o botão. Código do `_arm_notification_keepalive` ainda
  existe mas nunca é chamado; será removido depois de
  confirmar estabilidade.

## [0.42.3] — 2026-05-20

### Corrigido
- **Barra de seleção deslocava o conteúdo do card e desalinhava
  a linha de status entre consoles** (`ui/terminal_child_widget.py`):
  o `_selection_strip` (2px branco à esquerda) usava
  `setVisible(True/False)`, e ao ficar invisível saía do fluxo do
  `QHBoxLayout` — então o card selecionado ficava 2px + spacing à
  direita dos outros, fazendo "Trabalhando" / "Ocioso · …" não
  alinharem horizontalmente entre cards. Agora a strip fica sempre
  no layout (largura fixa reservada) e só a cor alterna entre
  branca (selecionado) e transparente (não selecionado).

## [0.42.2] — 2026-05-20

### Corrigido
- **Botão "Abrir console" ausente na primeira emissão**
  (`ui/main_window.py`): no KDE Plasma 6.6.5, popups com
  `replaces_id=0` renderizam SEM o botão de action — só
  re-emissões com `replaces_id != 0` mostram. Como o "Pronto"
  (working→idle) usa replaces_id=0 e o "Ainda aguardando"
  (reminder) usa replaces_id=nid_anterior, só o reminder tinha
  botão. Workaround: na primeira emissão, agenda re-emit em
  200ms via `QTimer.singleShot` — o popup atualizado já vem
  com botão. Keepalive normal de 5s assume depois.

## [0.42.1] — 2026-05-20

### Corrigido
- **Popup sumindo em 40ms apesar do keepalive**
  (`ui/main_window.py`): KDE Plasma 6.6.5 interpreta `timeout_ms=0`
  como "expira imediato" (~40ms — confirmado pelo log
  `NotificationClosed reason=expired age=0.04s`), em vez de "nunca
  expira" como manda a spec FDO. Voltamos a usar
  `settings.notify_timeout_ms` (default 10s); o keepalive de 5s
  re-emite antes do popup expirar, mantendo o banner visível.

## [0.42.0] — 2026-05-20

### Adicionado
- **Banner sticky no KDE via keepalive (QTimer re-emit)**
  (`ui/main_window.py`): KDE Plasma 6 transient-iza qualquer notif
  com action ignorando urgency/resident/transient. Workaround:
  `QTimer` por tab re-emite a notif a cada 5s com `replaces_id`,
  fazendo o banner reaparecer antes do Plasma matá-lo (~6s). O
  popup fica visualmente sticky. Cancelado quando o tab sai do
  inbox ou o usuário clica em "Abrir console". Outros apps
  (Telegram/KMail) só conseguem sticky porque usam KNotification
  nativa do KDE, que não tem binding Python decente.

## [0.41.0] — 2026-05-20

### Alterado
- **Footer da sidebar compactado em uma linha + menos chamadas
  à `/api/oauth/usage`** (`ui/main_window.py`, `plan_usage_api.py`):
  o bloco de "Uso do plano" ocupava 3-4 linhas (`Sessão 5h`,
  `Semana (todos)`, `Semana (Sonnet)`, linha de sync) e em cooldown
  virava um banner de 2 linhas (`API em cooldown / retry em Nmin · clique ⟳…`),
  empurrando os botões pra fora da tela em sidebars curtas. Agora
  vira chips inline `5h 34% · sem 41% · son 12%` com cores no número
  e detalhes (resets, fonte, timestamp de sync) movidos pro tooltip.
  Em cooldown: uma linha só, `Uso: cooldown 44m`.
- **TTL do cache `/api/oauth/usage` subiu de 60s pra 300s**
  (`plan_usage_api.py`): a Anthropic devolve `Retry-After` de até
  1h quando o limite é batido — 5min de TTL local é conservador o
  bastante pra raramente chegar nesse ponto sem perder responsividade
  visual.
- **Mudança de aba/workspace não dispara mais refresh do uso do plano**
  (`ui/main_window.py`): os handlers `currentChanged` do
  `terminal_host` e do `area.tabs` chamavam `_refresh_plan_usage_status`,
  mas o % de plano não muda ao alternar aba — só queimava cota. Só
  o poll de 5s do `_refresh_terminal_git_info` e o ⟳ manual dão refresh
  agora.

## [0.40.0] — 2026-05-20

### Adicionado
- **Apps auxiliares persistem a última URL entre execuções**
  (`ui/views/apps_view.py`): antes, ao reabrir o claude-workspaces
  os PWAs voltavam pra home (só os cookies sobreviviam). Agora cada
  app salva a URL atual em `apps_profiles/<slug>/state.json` com
  debounce de 800ms via `QTimer`, e na próxima abertura o `_AppPage`
  restaura essa URL em vez de chamar `_go_home()` — fim da sensação
  de F5 ao trocar de aba/relaunch. Entre abas na mesma sessão o
  estado já era preservado (cada `_AppPage` fica vivo no
  `QStackedWidget`).

## [0.39.2] — 2026-05-20

### Adicionado
- **Barra branca de seleção ao lado do strip de estado**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): com o bg
  da seleção zerado em 0.38.2, não dava pra saber qual console
  estava selecionado. Adicionada `_selection_strip` (QFrame 2px
  branco) encostada do lado direito do `_status_strip` — mesma
  altura, escondida por padrão, ligada/desligada pelo
  `_on_selection_changed` do MainWindow via `set_selected(bool)`.

### Melhorado
- **Logs de diagnóstico das notificações D-Bus**
  (`services/desktop_notifier.py`): pra investigar quando o
  popup some cedo demais no KDE. Agora logamos: identidade do
  servidor (`GetServerInformation`), capabilities completas,
  estado de DND no envio, hints/urgency/timeout/actions
  enviados, `note_id` aceito, `ActionInvoked` com idade do
  popup, e `NotificationClosed` com `reason` nomeado
  (expired/dismissed/closed_api) + idade. Se `reason=expired`
  com age<3s, o servidor ignorou `resident`/`urgency=critical`.

## [0.39.1] — 2026-05-20

### Corrigido
- **Banner sumindo rápido demais com o botão "Abrir console"**
  (`services/desktop_notifier.py`, `ui/main_window.py`): KDE Plasma 6
  tratava o popup como transient (~6s) assim que aparecia uma action.
  Agora mandamos urgency=2 (critical, sticky por padrão no KDE),
  hint `resident=true` (não some ao clicar a ação) e
  `transient=false` (entrada persistente na central), com
  `timeout_ms=0` pra deixar o servidor decidir quando some.

## [0.39.0] — 2026-05-20

### Adicionado
- **Notificação nativa — botão "Abrir console"**
  (`ui/main_window.py`): clique único no banner D-Bus leva direto pra
  aba certa do workspace, em vez de obrigar o usuário a garimpar pela
  sidebar. Tradeoff conhecido: no KDE Plasma 6 notificações com action
  viram transient (~6s), mas continuam acessíveis na central de
  notificações depois.

### Corrigido
- **Som da notificação no KDE Plasma**
  (`services/desktop_notifier.py`): canberra-gtk-play retornava sucesso
  mas o áudio saía mudo — vai pelo role "event-sounds" do PA/PipeWire,
  que o Plasma costuma deixar mutado por padrão. Agora preferimos
  `pw-play`/`paplay` (role "music", mesmo canal do áudio normal);
  canberra vira fallback.

## [0.38.2] — 2026-05-20

### Melhorado
- **Sidebar — sem background em hover/seleção**
  (`ui/builders/sidebar_builder.py`): qualquer tint no `::item`
  selecionado fazia o card destacar demais. Agora o background é
  totalmente transparente em todos os estados; a faixa vertical
  colorida (`_status_strip`) é a única pista visual de estado.

## [0.38.1] — 2026-05-20

### Removido
- **Linha "Uso (30d): in/out/cache · US$ X" no painel central de workspace**
  (`ui/workspace_details.py`): a info de custo/tokens não agrega muito
  no fluxo de abrir Claude/IDE e ainda destacava preço. Função
  `_refresh_usage` + label + chamada removidas.

### Adicionado
- **"Sessões recentes do Claude" colapsável** (`ui/workspace_details.py`):
  chevron `▾/▸` ao lado do título colapsa lista + filtro + botão de
  favoritos pra liberar espaço no painel central quando o usuário não
  está navegando histórico de sessões.

### Melhorado
- **Seleção da sidebar muito sutil — não parece mais "ativada"**
  (`ui/builders/sidebar_builder.py`): o bg `BG_SURFACE` cheio destacava
  o card selecionado demais e dava a impressão de algo "ligado" sem
  motivo. Trocado por tint branco a 5% (`rgba(255,255,255,0.05)`),
  com hover a 2.5% e selected+hover a 7%. Suficiente pra diferenciar,
  discreto pra não roubar atenção.

## [0.38.0] — 2026-05-20

### Melhorado
- **Redesign do card de console — menos linhas, layout consistente**
  (`ui/terminal_child_widget.py`, `ui/builders/sidebar_builder.py`,
  `ui/main_window.py`): a coluna do ícone spinner (`‖`/`⠋`) foi removida
  do layout — a faixa vertical de estado (`_status_strip`) já cumpre
  o papel de sinalizar idle/working/awaiting/done sem duplicar.
  Chips de modelo (`opus-4-7`) e branch (`⎇ main`) perderam border e
  background — viraram só texto colorido (model em azul `TEXT_LINK`
  bold, branch em cinza `TEXT_FAINT`). O `QTreeWidget::item` ficou
  sem qualquer border/separator: só mudança discreta de bg em
  hover/seleção — antes tinha 1px de borda lateral + border-bottom
  separador + bordas nos chips, somando "linhas demais". Statusline
  (`Context ▓▓▓ %`) ganhou `font-family: monospace` consistente.
  Altura do row caiu de 86 pra 82px (overhead do item caiu de 12px
  pra 8px sem as bordas).

## [0.37.9] — 2026-05-20

### Corrigido
- **Conteúdo do card de console transbordando + workspaces colados**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`,
  `ui/workspace_item_widget.py`): com a nova borda 1px do `::item` e o
  chip row de modelo+branch adicionados em 0.37.8, o widget interno
  (71px) ficou maior que a área útil do row (que perde 12px pra
  border+padding), e os chips/strip vertical estouravam o card. Altura
  do widget bumpada pra 74px e `_CHILD_HEIGHT` pra 86px (74 + 12 de
  overhead). Também adicionei 2px de margem esquerda pro `_status_strip`
  caber dentro da borda do item. Headers de workspace passaram de 28px
  pra 36px de altura mínima com 8px de padding-bottom — dá respiro
  entre workspaces que antes ficavam "colados" um no outro.

## [0.37.8] — 2026-05-20

### Melhorado
- **Sidebar — seleção como borda cinza ao redor e separador entre rows**
  (`ui/builders/sidebar_builder.py`): a linha azul vertical à esquerda
  do item selecionado foi trocada por uma borda 1px acinzentada (`BORDER`)
  envolvendo todo o row, com fundo `BG_SURFACE` discreto. Itens não
  selecionados ganharam um `border-bottom: 1px solid BORDER_SOFT` pra
  funcionar de separador sutil entre consoles adjacentes — fica claro
  onde um termina e outro começa sem chamar atenção. Hover usa cores
  intermediárias. Border-space total é constante em todos os estados
  (1px/lado) pra não shiftar o layout na transição idle → hover → selected.

### Adicionado
- **Diagnóstico das janelas fantasmas** (`app.py`): `_log_ghost_window_diagnostics`
  dumpa no `app.log` em 3 fases (T=0, +500ms, +2000ms após `window.show()`):
  env vars (`XDG_SESSION_TYPE`, `WAYLAND_DISPLAY`, `QT_QPA_PLATFORM`,
  `QTWEBENGINE_CHROMIUM_FLAGS` etc), todos `QApplication.topLevelWidgets()`
  com tipo/título/visibilidade/geom/flags/parent, subprocessos
  `QtWebEngineProcess` filhos do nosso PID, e contagem de janelas com
  "Claude" no título reportadas pelo `qdbus6 KWin WindowsRunner`. Linhas
  prefixadas `[GHOST-DIAG]` em WARNING pra ficar fácil de filtrar.

## [0.37.7] — 2026-05-20

### Corrigido
- **Janelas fantasmas vazias na overview do Plasma Wayland** (`app.py`):
  sob KDE Plasma 6 Wayland, cada subprocesso do `QtWebEngineProcess`
  registra surface wayland própria com `--application-name=Claude
  Workspaces` e aparece como janela vazia na overview (Meta+W). Como
  cada `QWebEngineView` (xterm.js dos terminais, runners, apps) spawn
  um renderer separado, o número de janelas fantasmas crescia com a
  quantidade de views. Solução: setar `QTWEBENGINE_CHROMIUM_FLAGS=--ozone-platform=x11`
  antes de qualquer import do QtWebEngine — o app principal continua
  no Wayland (sem perder HiDPI), mas o Chromium embarcado usa
  X11/XWayland e os renderers não criam mais surfaces avulsas. A
  correção anterior (0.37.6, `_SameViewPage` no `apps_view`) atacava
  outra fonte de janelas extras (`window.open()` das webapps) e
  continua valendo.

## [0.37.6] — 2026-05-20

### Melhorado
- **Sidebar — faixa de estado à esquerda e branch/modelo como chips
  alinhados** (`ui/terminal_child_widget.py`): cada row de console
  ganhou uma faixa vertical de 3px no canto esquerdo pintada com a
  cor do estado (vermelho=ocioso, âmbar=trabalhando, laranja=aguardando,
  verde=concluído) — passa o estado de cada console em um glance, em
  vez de depender só da linha de seleção monocromática. A branch saiu
  do label solto vertical-center no canto direito do card e virou um
  chip ao lado do chip do modelo (`opus-4-7`), na mesma linha — antes
  ficavam desalinhados verticalmente.

### Corrigido
- **Janelas brancas vazias abrindo sozinhas na barra de tarefas**
  (`ui/views/apps_view.py`): webapps embutidos (ClickUp/Taskis/etc)
  chamam `window.open()` pra popups de OAuth, preview e "Abrir em
  nova guia". Sem override do `createWindow` no `QWebEnginePage`, o
  Qt cria essas popups como janelas top-level vazias que aparecem na
  taskbar e voltam a abrir quando fechadas (a página re-chama
  `window.open` quando o popup some). Nova subclasse `_SameViewPage`
  intercepta o `createWindow`, devolve uma página descartável que
  captura a primeira URL e redireciona pra view principal —
  popup vira navegação na mesma aba.

## [0.37.5] — 2026-05-20

### Corrigido
- **Sidebar ainda pulando workspace ao mover o mouse — segunda
  iteração** (`ui/builders/sidebar_builder.py`): a defesa do 0.37.4
  só bloqueava `mouseMove` com botão esquerdo segurado, mas o switch
  do mouse com chatter dispara `press` espúrios durante o movimento —
  o cursor "descendo" entre rows registra novos cliques no item abaixo.
  Agora: (1) `mouseMoveEvent` é descartado SEMPRE (com ou sem botão);
  (2) `mousePressEvent` com debounce de 120ms — qualquer press esquerdo
  que chegue mais perto que isso do anterior é considerado chatter e
  não chega ao base. Combinado com o restore-no-release do 0.37.4,
  fecha o caminho do bug pra qualquer combinação plausível de eventos
  espúrios do switch defeituoso.

## [0.37.4] — 2026-05-20

### Corrigido
- **Seleção da sidebar pulando pra outro workspace ao clicar num
  console** (`ui/builders/sidebar_builder.py`): subclass `_StableTree`
  do `QTreeWidget` ignora drag de seleção. No comportamento padrão,
  com o botão esquerdo pressionado, `currentItem` segue o cursor —
  qualquer micro-arrasto entre rows muda a seleção. Mouse com chatter
  no switch do botão esquerdo dispara press+move+release sobre
  múltiplos itens num "clique único", fazendo a seleção pular pro
  último item sob o ponteiro (sintoma reportado: clicar num console
  e cair em outro workspace). Agora: na `MoveEvent` com botão
  esquerdo segurado, o evento não é propagado pra base — seleção
  trava no item do press; no `release`, se o ponteiro saiu do item
  original, restauramos a seleção pro item onde o press começou.

## [0.37.3] — 2026-05-20

### Corrigido
- **Placeholder "Nova sessão do claude…" cortando texto**
  (`ui/main_window.py`): altura do row aumentada de 24px para 30px e
  padding vertical voltou para 4px (com `setMinimumHeight(24)` no
  botão) — o texto estava sendo clipado quando a row ficou pequena
  demais na tentativa anterior.

## [0.37.2] — 2026-05-20

### Corrigido
- **Estado "Ocioso" voltou pra esquerda; ações inline na mesma linha à
  direita** (`ui/terminal_child_widget.py`): após mover a statusline
  pra linha própria (0.37.0), o `state_label` ficou centralizado
  porque era o único item flutuante no row. Adicionado `addStretch`
  e movido o bloco de ações (▶ ⚙ ✖) pro mesmo `sub_row` —
  resultado: "Ocioso · 4s" colado na esquerda, ações empurradas pra
  direita, sem mudar a altura do row.

## [0.37.1] — 2026-05-20

### Corrigido
- **Diálogo "Remover console" com ícones invisíveis no tema escuro**
  (`ui/main_window.py`): o `QMessageBox.question` padrão renderizava
  os botões Yes/No com glifos quase invisíveis sobre fundo escuro.
  Substituído por `QMessageBox` customizado com botões "Sim"/"Não"
  em PT-BR sem ícone — fica legível e mais consistente com o resto
  da UI.

## [0.37.0] — 2026-05-20

### Alterado
- **Última ação (statusline do Claude) ganha linha própria na sidebar**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): antes, o texto
  capturado da statusline (ex.: `Context ▓▓▓ 7% · Usage …`) aparecia
  colado ao "Ocioso · 12m 15s", poluindo a linha de estado. Agora ele
  fica numa linha dedicada entre o estado e o nome do modelo
  (`opus-4-7`). A altura do row da sidebar subiu de 58 → 71px pra caber
  a 4a linha.

## [0.36.0] — 2026-05-20

### Adicionado
- **Atalhos "sem contexto" agora embutidos** (`ui/main_window.py`,
  `ui/builders/sidebar_builder.py`): os botões "›_ Abrir Terminal" e
  "✦ Claude (sem contexto)" da sidebar não abrem mais janela externa
  do konsole — abrem uma aba nova **dentro do app**, numa
  `TerminalArea` dedicada ("sem ctx") que vive no `terminal_host`
  central. Cada clique adiciona mais uma aba, o foco vai pra ela
  automaticamente, e as abas persistem mesmo trocando de workspace
  (basta voltar a clicar pra reanexar a area).

### Removido
- `launchers.launch_terminal_no_ctx` / `launch_claude_no_ctx`: não
  têm mais chamadores depois da migração pra embutido.

## [0.35.2] — 2026-05-20

### Alterado
- **Som de notificação — logging mais útil**
  (`services/desktop_notifier.py`): sucesso do `canberra-gtk-play` /
  `paplay` / `pw-play` agora loga em **INFO** (antes era DEBUG, então
  não aparecia no `app.log` com root em INFO — não dava pra confirmar
  se o som tinha sido disparado). Também capturamos `stderr` mesmo
  quando `rc=0` e logamos se vier não-vazio, porque o canberra às
  vezes alerta sobre cache do tema ou sample faltando sem falhar de
  fato. Sem mudança de comportamento — só telemetria.

## [0.35.1] — 2026-05-20

### Alterado
- **Placeholder de workspace vazio** (`ui/main_window.py`): botão renomeado
  de "Abrir Claude aqui" para "Nova sessão do claude…" e padding/altura
  reduzidos para caber na largura da sidebar sem cortar a borda
  tracejada.

## [0.35.0] — 2026-05-20

### Adicionado
- **Status de fase do runner na sidebar**
  (`ui/runner_widget.py`, `ui/runner_area.py`, `ui/runner_child_widget.py`,
  `ui/main_window.py`): cada linha de runner na sidebar agora exibe uma
  segunda linha curta com a fase atual (`reiniciando`, `parando`,
  `carregando`) quando o runner está em transição. Estados estáveis
  (`rodando`, `parado`, `erro`) continuam representados só pela bolinha
  colorida — a linha extra só aparece pra dar pista visual durante
  fases transientes. Implementado via novo `status_changed` em
  `RunnerWidget` + forward `runner_status_changed` em `RunnerArea`,
  consumidos por `RunnerChildWidget.set_status()` que reajusta o
  `sizeHint` do item da tree.

## [0.34.1] — 2026-05-20

### Mudado
- **Cursor pointer em locais clicáveis da sidebar**
  (`ui/builders/sidebar_builder.py`): os botões "＋ Novo Workspace",
  "›_ Abrir Terminal", "✦ Claude (sem contexto)" e "🔧 Hack este app"
  agora trocam o cursor pra mãozinha no hover, igual aos botões inline
  dos rows. A árvore de workspaces/consoles também passou a usar
  pointer cursor — sinaliza melhor que os itens são clicáveis.

## [0.34.0] — 2026-05-20

### Adicionado
- **Placeholder "＋ Abrir Claude aqui" em workspace vazio**
  (`ui/main_window.py`): quando um workspace não tem nenhum console nem
  runner rodando, expandi-lo na sidebar agora mostra um botão tracejado
  "＋ Abrir Claude aqui" como filho — mesma ação do botão + no header
  do workspace, mas evita o "nada acontece" visual de antes. Some
  sozinho quando o primeiro console/runner aparece e volta quando o
  último é fechado. Marcado via UserRole sentinel
  `__empty_workspace_placeholder__`; ignorado pelos handlers existentes
  (que só reagem a `int`/`tuple`).

- **Atalhos de sidebar "Abrir Terminal" e "Claude (sem contexto)"**
  (`ui/builders/sidebar_builder.py`, `ui/main_window.py`,
  `launchers.py`): dois novos botões ghost logo abaixo de "Novo
  Workspace" — abrem uma janela nova do terminal (konsole por padrão,
  via `settings.terminal_command`) em `$HOME`, sem workspace nenhum.
  O primeiro só abre o shell; o segundo já roda `claude` dentro.
  Úteis pra perguntas avulsas que não pertencem a um projeto. Novas
  funções `launch_terminal_no_ctx` e `launch_claude_no_ctx` em
  `launchers.py`.

## [0.33.0] — 2026-05-20

### Adicionado
- **Host:port dos runners na sidebar**
  (`ui/runner_child_widget.py`, `ui/runner_widget.py`, `ui/runner_area.py`,
  `ui/main_window.py`): a linha de cada runner na sidebar agora mostra
  `host:port` ao lado do nome quando há URL conhecida — seja pela
  detecção automática (`open_browser_on_ready`) ou pelo campo
  `browser_url` da config. Vazio = label oculta, mantém o layout
  compacto. URL detectada em tempo real propaga via novo signal
  `RunnerWidget.url_changed` → `RunnerArea.runner_url_changed` →
  `MainWindow._on_runner_url_changed`.

- **Delay configurável p/ abrir o browser dos runners**
  (`settings.py`, `ui/settings_panel.py`, `ui/runner_widget.py`): novo
  setting global `browser_open_delay_ms` (default 5000ms, antes era
  hardcoded em 400ms). Why: servers tipo Glassfish/Spring Boot logam
  a URL antes do listener aceitar conexões — 400ms não era suficiente
  e o browser batia em ECONNREFUSED. 5s cobre cold start desses
  servers sem ficar perceptível em devservers rápidos. Configurável
  em **Configurações → Delay p/ abrir browser**.

- **Padrão de pronto (`ready_pattern`) nos runners**
  (`models.py`, `ui/runner_edit_dialog.py`, `ui/runner_widget.py`):
  novo campo opcional regex case-insensitive aplicado na stdout do
  runner. Quando preenchido, o browser só abre depois que o padrão
  casa. Útil pra Glassfish/Tomcat, onde a porta sobe antes do deploy
  terminar (ex: `Application \[ogpms\] deployed`). Vazio mantém o
  comportamento antigo (abre na primeira URL detectada).

## [0.32.1] — 2026-05-20

### Corrigido
- **Logs de falha ao tocar som da notificação**
  (`services/desktop_notifier.py`): antes usávamos `subprocess.Popen`
  com `stderr=DEVNULL` pra tocar `canberra-gtk-play`/`paplay`/`pw-play`
  em background — qualquer falha (cache do canberra vazio, sample
  ausente, sem acesso ao pulse) era engolida silenciosamente e o
  usuário via "notificação sem som" sem nenhuma pista. Agora rodamos
  em thread daemon com `subprocess.run` capturando stderr e logamos
  o motivo (`rc`, stderr truncado) no `app.log`. Ajuda a
  diagnosticar quando o som não toca.

## [0.32.0] — 2026-05-20

### Adicionado
- **Botão ✖ pra remover console direto da sidebar**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): antes só dava
  pra encerrar/remover um console pelo menu de contexto (clique direito
  → "Encerrar/remover console"). Agora o row tem um botão ✖ inline ao
  lado de ▶ e ⚙, com hover em vermelho pra deixar claro que é
  destrutivo. Pede confirmação antes (mensagem muda se o processo está
  rodando ou já encerrado). Visibilidade segue o mesmo toggle do header
  WORKSPACES (`show_terminal_actions`); o ✖ fica habilitado mesmo em
  console já encerrado pra permitir limpar a sidebar.

## [0.31.0] — 2026-05-20

### Adicionado
- **Duração configurável do banner de notificação** (`settings.py`,
  `ui/settings_panel.py`, `ui/main_window.py`): novo campo
  `notify_timeout_ms` (default 10000 = 10s) controla o tempo de
  exibição do banner. Antes usávamos `-1` (default do SO), o que
  fazia o banner sumir em ~5s no KDE Plasma respeitando a config
  "Show pop-ups for X seconds". Agora dá pra forçar um tempo maior
  sem mexer no painel do SO. Valores aceitos: `-1` mantém o
  comportamento antigo (default do servidor), `0` deixa sticky
  (banner não some sozinho), `>0` força o tempo em ms. Ajustável
  no painel de Configurações → Notificações → "Duração do banner".

## [0.30.2] — 2026-05-20

### Mudado
- **Sidebar mostra só o modelo na 3a linha do card**
  (`ui/terminal_child_widget.py`): os números de `ctx %`, `in`, `out` e
  `cache` que apareciam ao lado do modelo estavam fora do que realmente
  reflete o estado da sessão e geravam confusão. Agora a linha exibe
  apenas o modelo encurtado (ex.: `opus-4-7`); custo e detalhes continuam
  acessíveis pelo menu de contexto.

## [0.30.1] — 2026-05-20

### Corrigido
- **Som não tocava no KDE Plasma 6**
  (`services/desktop_notifier.py`, `packaging/notify-hook.py`): Plasma
  6 ignora silenciosamente a hint `sound-name` do D-Bus (bug histórico
  do plasma-workspace). Agora tocamos o sample nós mesmos via
  `canberra-gtk-play` (respeita o tema sonoro atual), com fallback pra
  `paplay`/`pw-play` no `.oga` em `/usr/share/sounds/freedesktop/stereo`.
  A hint continua sendo enviada pro D-Bus pra honrar quem implementa
  (GNOME Shell, dunst).

## [0.30.0] — 2026-05-20

### Adicionado
- **Som nas notificações nativas** (`settings.py`,
  `services/desktop_notifier.py`, `ui/main_window.py`,
  `ui/settings_panel.py`, `packaging/notify-hook.py`): notificações de
  "Pronto" / "Ainda aguardando" e o hook Stop do Claude Code agora
  enviam a hint `sound-name` do D-Bus (`org.freedesktop.Notifications`),
  fazendo o servidor (KDE Plasma, GNOME Shell, dunst) tocar o sample
  correspondente do tema sonoro via libcanberra. Default é
  `message-new-instant`. Configurável em Configurações → Notificações
  (checkbox "Tocar som nas notificações nativas" + campo "Nome do som")
  — aceita qualquer nome XDG (`message`, `complete`, `bell`,
  `alarm-clock-elapsed`, …). Novos campos em settings.json:
  `notify_sound_enabled`, `notify_sound_name`.

## [0.29.0] — 2026-05-19

### Adicionado
- **Estado colapsado da sidebar persiste entre sessões**
  (`settings.py`, `ui/main_window.py`,
  `ui/workspace_item_widget.py`, `ui/runner_group_widget.py`): o app
  agora salva, por workspace, se o próprio workspace está recolhido e
  se o submenu "Runners workspace" está recolhido. Antes, tudo voltava
  expandido ao reabrir o app — desperdiçava espaço pra quem trabalha
  com muitos workspaces. Persistência em
  `~/.config/claude-workspaces/settings.json` (campos novos
  `workspace_collapsed`, `runner_group_collapsed`). Runner groups de
  console não são persistidos porque o `tab_id` não é estável entre
  sessões.

### Alterado
- **Ícone de colapsar trocado de triângulo pra chevron**
  (`ui/workspace_item_widget.py`, `ui/runner_group_widget.py`): `▾`/`▸`
  viraram `⌄`/`›`. O triângulo apontado pra direita estava ficando muito
  parecido com o botão de play (▶) dos runners na mesma linha — gerava
  confusão visual.

## [0.28.1] — 2026-05-19

### Corrigido
- **Runner-gen ignorava o prompt inicial** (`ui/main_window.py`,
  `services/runner_prompt.py`, `docs/runners-spec.md`): no 0.27.1 a
  tela preta sumiu, mas o Claude CLI 2.1.x tem outro comportamento
  surpreendente — quando lançado com `--add-dir` **+** prompt
  posicional, ele descarta o prompt silenciosamente e abre só o
  welcome screen vazio. Como já passamos `--dangerously-skip-permissions`,
  o `--add-dir` virou redundante (claude lê os paths absolutos do spec
  e das pastas extras via Read). Removido o `--add-dir` do launch de
  runner-gen — o prompt agora é entregue de verdade e o Claude começa
  a investigar imediatamente. O prompt foi ajustado pra deixar
  explícito que os paths absolutos do workspace devem ser lidos via
  Read/Glob/LS.

## [0.28.0] — 2026-05-19

### Adicionado
- **Dialog "Abrir Claude" mais compacto + prompt inicial opcional**
  (`ui/launch_claude_dialog.py`,
  `ui/coordinators/launch_coordinator.py`): modal reduzido de 640×460
  → 560×420, com spacing apertado (10→6), header consolidado numa
  linha só (workspace + dica de cwd/`--add-dir`), e a seção Git
  colapsada num único `<b>Git:</b> branch atual …`. Novo campo
  `Prompt inicial (opcional)` (`QPlainTextEdit` de 64 px) — se
  preenchido, o coordinator agenda um `send_text` via `QTimer` 1.5 s
  depois do spawn pra digitar o prompt na TUI do Claude como se fosse
  o usuário. Optei por send_text via PTY em vez de prompt posicional
  no argv pra evitar a regressão de tela preta documentada em 0.27.1
  quando há `--add-dir` + prompt grande.

## [0.27.1] — 2026-05-19

### Corrigido
- **Runner-gen ficava com tela preta** (`services/runner_prompt.py`,
  `docs/runners-spec.md`): o Claude CLI 2.1.x trava na PTY (não
  renderiza nada) quando recebe `--add-dir` + prompt posicional acima
  de ~500 chars. O prompt do gerador tinha ~6 KB com toda a instrução
  inline, fatal. Movida a instrução de investigação (Passo 1/2/2.5/3/4)
  e o formato de saída pro próprio `docs/runners-spec.md` (que o Claude
  já lê via `--add-dir`); o prompt agora é um ponteiro curto de ~450
  chars. Claude renderiza imediatamente e segue o spec via Read.

## [0.27.0] — 2026-05-19

### Adicionado
- **Botão "↻ Retomar geração com Claude" no dialog de edição do
  runner** (`models.py`, `runners_io.py`, `ui/runner_edit_dialog.py`,
  `ui/runner_area.py::_reload_from_draft`, `ui/main_window.py`):
  `RunnerConfig` ganhou `gen_session_id` + `gen_cwd`, stampados em
  `import_runners` quando o reload vem do rascunho de runner-gen
  (consulta `runner_gen_history` pra pegar a entrada mais recente do
  workspace). No dialog de edição, quando esses campos existem
  aparece um botão que chama `_resume_runner_gen_session` —
  `claude --resume <id>` no cwd original com `--add-dir` reaplicado
  pro repo do claude-workspaces e pastas extras. Permite pedir
  ajustes no runner sem perder o contexto da conversa de geração.
  Os campos `gen_*` são removidos no export portável (referenciam
  JSONL local).

## [0.26.4] — 2026-05-19

### Alterado
- **runner-gen agora roda no cwd do projeto do usuário, não do
  claude-workspaces** (`ui/main_window.py::_generate_runner_with_claude`,
  `services/runner_prompt.py`): antes o Claude da geração era lançado
  com `cwd = repo do claude-workspaces` pra conseguir ler
  `docs/runners-spec.md` — efeito colateral: o JSONL ficava em
  `~/.claude/projects/<claude-workspaces>` e a sessão aparecia
  associada ao projeto errado. Agora o `cwd` é a primeira pasta do
  workspace (igual ao botão "Abrir Claude"), `docs/runners-spec.md`
  vai por caminho absoluto no prompt, e o repo do claude-workspaces
  + pastas extras entram via `--add-dir`. A retomada (`--resume`)
  reaplica os mesmos `--add-dir`. O índice de runner-gen passa a
  guardar o `cwd` do projeto, então `claude --resume` resume no
  lugar certo.

## [0.26.3] — 2026-05-19

### Corrigido
- **Painel não mostra mais o fallback USD durante cooldown da API**
  (`main_window.py::_refresh_plan_usage_status`): o fallback estimado
  por preços públicos da API é tão impreciso pra Max 5x que mostrava
  números absurdos (caso real: 100% no painel logo após o reset da
  sessão, quando claude.ai mostrava 0%). Agora, quando a API está em
  cooldown explícito (HTTP 429 com `Retry-After`), o painel troca os
  3 %s por "API em cooldown · retry em Xmin · clique ⟳ depois disso
  pra sincronizar" — informação honesta vale mais que estimativa
  errada. Quando a API responde, os números voltam normalmente.

## [0.26.2] — 2026-05-19

### Adicionado
- **Botão ⟳ no painel de uso do plano** (`sidebar_builder.py`,
  `main_window.py`) que força chamada nova ao `/api/oauth/usage`
  ignorando cache + cooldown negativo — útil quando o número parece
  travado e você quer ver o estado atual sem esperar o ciclo de 60s.
  Logo abaixo das 3 linhas de %, o painel agora exibe
  `sync HH:MM:SS · API` ou `sync HH:MM:SS · fallback USD (cooldown
  Xmin)` em cinza-escuro pequenininho, deixando claro qual fonte foi
  consultada e quando. Sem isso o painel parecia "vivo" mesmo quando
  o fallback servia números desatualizados.

### Mudado
- **Notificações de console pronto usam o tempo padrão do SO**
  (`main_window.py::_handle_alert`): antes forçávamos `urgency=critical
  + timeout_ms=300000` (5min), o que ignorava a preferência "Show
  pop-ups for X seconds" do servidor de notificações. Agora mandamos
  `urgency=normal + timeout_ms=-1` (default freedesktop = "servidor
  decide"), então o popup respeita o tempo configurado pelo usuário em
  System Settings → Notifications.

## [0.26.1] — 2026-05-19

### Corrigido
- **`plan_usage_api` agora respeita `Retry-After` em 429**
  (`plan_usage_api.py`): em vez de retentar a cada 60s, o cache
  negativo passa a durar exatamente o que a Anthropic pediu (até
  3600s). Sem isso, qualquer retry durante o bloqueio só reinicia o
  contador. User-Agent ajustado pra `claude-code/2.1.144` (imita a CLI
  oficial — UA desconhecido recebia 429 mais agressivo). Tooltip do
  painel agora mostra "API em cooldown (Xmin restantes)" quando o
  fallback USD-baseado está sendo usado por rate-limit, deixando claro
  por que os números divergem do claude.ai temporariamente.

## [0.26.0] — 2026-05-19

### Adicionado
- **Painel de uso do plano agora consome `/api/oauth/usage`** (mesmo
  endpoint que o `/status` do Claude Code) — os % de Sessão 5h, Semana
  (todos) e Semana (Sonnet) agora batem exatamente com o que o
  claude.ai mostra, em vez de estimar dividindo o custo USD acumulado
  por um limite calibrado na mão. Caso típico antes desta mudança:
  painel exibia "Sessão 5h: 59%" enquanto o claude.ai mostrava 21% —
  divergência inevitável porque a Anthropic não publica a conversão
  token→cota e o limite USD era arbitrário. Novo módulo
  `plan_usage_api.py` lê o `accessToken` de
  `~/.claude/.credentials.json`, chama o endpoint com cache de 60s
  (mais cache negativo se rate-limited ou token expirado), e devolve
  utilização + `resets_at` por bucket (`five_hour`, `seven_day`,
  `seven_day_opus`, `seven_day_sonnet`). O reset agora vem direto da
  API, então a divergência de minutos no "reset NhNNm" (causada por
  usar o `first_ts` do JSONL local em vez do início real da sessão
  Anthropic) também some.
- **Fallback transparente pro cálculo USD-baseado** quando a API
  falha (token expirado, offline, rate-limit). Tooltip identifica
  qual fonte foi usada.

## [0.25.1] — 2026-05-19

### Corrigido
- **`pty_session.terminate` agora cumpre o SIGKILL fallback prometido
  no docstring** (`pty_session.py`): o comentário já dizia "SIGKILL é
  fallback se o group ainda existe ~300ms depois", mas a implementação
  só mandava SIGTERM e seguia. Resultado: ao reiniciar o app com um
  runner pesado rodando (caso real: `asadmin start-domain` do
  GlassFish do ogpms), o `java` filho ficava órfão e continuava
  ocupando memória/swap após o app fechar. Agora, 600 ms depois do
  SIGTERM, um `QTimer.singleShot` checa se o pgid ainda existe
  (`killpg(pid, 0)`) e, em caso positivo, manda `SIGKILL` no grupo
  inteiro.

## [0.25.0] — 2026-05-19

### Adicionado
- **Histórico de sessões de runner-gen com retomada**
  (`services/runner_gen_history.py`, `ui/runner_gen_dialog.py`,
  `ui/main_window.py`): toda vez que você clica em "Gerar com Claude"
  no dialog de runner, persistimos `{workspace_id, session_id, cwd,
  hint, created_at}` num arquivo dedicado
  (`~/.config/claude-workspaces/runner_gen_sessions.json`),
  independente da aba ainda estar aberta no fechamento do app. O
  antigo `QInputDialog.getText` foi substituído por um
  `RunnerGenDialog` com campo de hint, lista das gerações anteriores
  do workspace (mais recentes primeiro), filtro por texto, e botões
  "↻ Retomar selecionada" (faz `claude --resume <id>` no cwd
  original) e "Esquecer" (remove do índice). Entradas cujo JSONL
  sumiu do disco aparecem cinzas e não dá pra retomar.

## [0.24.9] — 2026-05-19

### Corrigido
- **Inbox alert respeita "Não perturbe"**
  (`services/desktop_notifier.py`, `ui/main_window.py`): antes a
  notificação ia sempre como `urgency=2` (critical), que bypassa DND
  por design do freedesktop. Agora consultamos a property `Inhibited`
  em `org.freedesktop.Notifications` via D-Bus e, quando DND está
  ativo, rebaixamos pra `urgency=1` + timeout 6s. Fora do DND
  segue critical/sticky de 5min como antes. Novo método
  `DesktopNotifier.inhibited()`.

## [0.24.8] — 2026-05-19

### Adicionado
- **Sidebar pisca quando sessão está "Aguardando"**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): o label
  "Aguardando" agora alterna entre laranja e branco a cada segundo,
  chamando atenção visual pra qual console o Claude pediu decisão.
  Aproveita o timer de 1s já existente (`_idle_tick_timer`), via
  novo método `tick_awaiting()`. Sair do estado AWAITING reseta a cor.

## [0.24.7] — 2026-05-19

### Mudado
- **Inbox alert agora vai sem actions clicáveis pra ganhar
  comportamento sticky** (`ui/main_window.py`): KDE Plasma 6 trata
  qualquer notificação com `actions` como transient (popup vai pro
  tray em ~6s) — comportamento testado exaustivamente que ignora
  urgency=critical, timeout_ms=300000, e todos os hints conhecidos
  (resident, transient=false, x-kde-display-appname). Como prioridade
  é não perder o aviso de "Claude precisa de você", removemos as
  actions ("Abrir console", "Adiar 5 min", "Já vi"). Interação
  passa a ser via sidebar/inbox dentro do app. Log temporário em
  `services/desktop_notifier.notify` mantido pra investigação.

## [0.24.6] — 2026-05-19

### Corrigido
- **Popup do banner sumia rápido mesmo com urgency=critical**
  (`services/desktop_notifier.py`, `ui/main_window.py`): KDE Plasma 6
  trata `expire_timeout=0` como "fica no histórico pra sempre" mas o
  popup ainda obedece o setting global "Show pop-ups for X seconds"
  (~6s default). Mudei o inbox alert pra usar `timeout_ms=300000`
  (5min) — força o popup a ficar visível enquanto isso. Também
  passamos a hint `desktop-entry='claude-workspaces'` pro Plasma
  reconhecer o app em System Settings → Notifications → Applications
  (permite override per-app).

## [0.24.5] — 2026-05-19

### Adicionado
- **Click no banner foca o console**
  (`ui/main_window.py`): registramos a ação especial `default` (do
  spec D-Bus de notificações) que dispara quando o usuário clica em
  qualquer parte do banner — não só nos botões. Aponta pro mesmo
  handler de "Abrir console". Antes só os 3 botões eram clicáveis.

## [0.24.4] — 2026-05-19

### Corrigido
- **Notificação nativa sumia rápido demais**
  (`services/desktop_notifier.py`, `ui/main_window.py`): o alerta de
  inbox usava `timeout_ms=8000` sem `urgency`, então em alguns
  ambientes o banner sumia antes do usuário ver. Adicionei
  parâmetro `urgency` em `DesktopNotifier.notify` (mapeia pra hint
  D-Bus padrão) e o alerta de inbox agora dispara com `urgency=2`
  (critical) + `timeout_ms=0` (não expira). GNOME/KDE mantêm
  notificações critical sticky até interação do usuário.

## [0.24.3] — 2026-05-19

### Corrigido
- **Notificação nativa não disparava na transição idle→awaiting**
  (`ui/coordinators/terminal_coordinator.py`): o `inbox_alert` só
  emitia quando a sessão saía de `working`, então pickers que
  apareciam direto de idle (caso típico quando o frame de "working"
  é curto demais pro parser de 250ms pegar) ficavam mudos. Agora
  também dispara quando `needs_decision` transita de False→True,
  rastreando `_prev_needs_decision` por tab. Cleanup correspondente
  em `_on_tab_removed` e `release_workspace`.

## [0.24.2] — 2026-05-19

### Corrigido
- **Sessões recentes do Claude não apareciam para projetos com espaço/underscore
  no caminho** (`claude_sessions.py`): o encoder de path só trocava `/` por `-`,
  mas o Claude Code também converte espaços, `_` e `.` para `-` ao nomear a
  pasta em `~/.claude/projects/`. Resultado: projetos como
  `/home/italo/Projetos/SIPE Sistemas/ponto_python_antigo/api` nunca casavam
  com o diretório real `-home-italo-Projetos-SIPE-Sistemas-ponto-python-antigo-api`
  e o painel mostrava "nenhuma sessão encontrada". Agora qualquer caractere
  não-alfanumérico vira `-`.

## [0.24.1] — 2026-05-19

### Corrigido
- **Picker do Claude aparecia como "Ocioso" em vez de "Aguardando"**
  (`claude_activity.py`): o TUI emite o footer
  `Enter to select · ↑/↓ to navigate · Esc to cancel` usando cursor
  positioning absoluto entre palavras, e `strip_ansi` remove os
  escapes sem reinserir espaços, resultando em
  `Entertoselect·↑/↓tonavigate·Esctocancel`. A detecção que dependia
  da regex literal `"enter to select"` falhava, e o mesmo acontecia
  com o permission prompt `"Do you want..."`. `_has_decision_prompt`
  agora normaliza as linhas (lowercase + remove não-alfanuméricos)
  antes de comparar, casando ambas as formas.

## [0.24.0] — 2026-05-19

### Adicionado
- **Cronômetro de ociosidade na sidebar**
  (`ui/terminal_child_widget.py`, `ui/main_window.py`): o label
  "Ocioso" agora é renderizado em vermelho (`theme.DANGER`) e exibe o
  tempo decorrido desde a última atividade — `Ocioso · 45s`,
  `Ocioso · 2m 30s`, `Ocioso · 1h 05m`. Um `QTimer` de 1s no
  `MainWindow` chama `tick_idle()` em cada `TerminalChildWidget`, que
  só atualiza se estiver em `STATE_IDLE`. Cronômetro reseta a cada
  transição de estado (entrar de novo em idle recomeça do zero).

## [0.23.1] — 2026-05-19

### Corrigido
- **Botão `+` no workspace não trocava o projeto selecionado**
  (`ui/main_window.py`): ao clicar `+` num workspace diferente do
  atualmente selecionado na sidebar, o console novo era aberto, mas
  o painel de detalhes (à direita) e `_current_workspace()` continuavam
  apontando pro projeto anterior. Agora o handler `on_add` em
  `_install_workspace_item_widget` chama
  `list_widget.setCurrentItem(item)` antes de `_launch_claude_for`,
  garantindo que o workspace alvo do `+` vire o ativo.

## [0.23.0] — 2026-05-19

### Adicionado
- **Botão "Abrir console" nas notificações do hook Stop**
  (`packaging/notify-hook.py`, `ui/main_window.py`,
  `services/desktop_notifier.py`): o `notify-hook.py` passou a emitir a
  notificação via `gdbus call ... .Notify` com a ação
  `open-console:<session_id>`, em vez do `notify-send` plano. O
  `MainWindow` escuta o sinal D-Bus `ActionInvoked` globalmente e, ao
  receber essa chave, encontra o `TerminalWidget` com
  `claimed_session_id` correspondente e foca o workspace + aba dentro
  do app. Fallback automático pra `notify-send` quando `gdbus` ou o
  servidor de notificações não suportam ações.
- **Auto-refresh do hook instalado** (`hook_manager.py`,
  `ui/main_window.py`): nova função `refresh_installed_hook()` é
  chamada no startup e re-copia o `notify-hook.py` packaged sobre o
  instalado em `~/.config/claude-workspaces/` quando difere do source.
  Evita ter que toggleear Remover/Ativar notificações manualmente pra
  pegar updates do script após um upgrade da app.

## [0.22.0] — 2026-05-19

### Adicionado
- **Numeração sequencial dos consoles na sidebar** (`ui/main_window.py`):
  cada console agora exibe `#N` antes do nome, com N reiniciado por
  workspace e atribuído por ordem de criação (tab_id crescente). Ao
  fechar um console, os demais são renumerados automaticamente via
  `_refresh_workspace_child_titles`. Substitui o sufixo `(N)` que só
  aparecia em colisões de nome — agora todo console tem um identificador
  visual estável dentro do seu workspace.

## [0.21.2] — 2026-05-19

### Corrigido
- **Console novo não aparecia/quebrava a sidebar** (`ui/main_window.py`):
  `_add_terminal_child` referenciava `ws_data` sem definir a variável
  no escopo da função, levantando `NameError` toda vez que um novo
  console era adicionado ao tree do workspace. Em re-listagens, a
  exceção interrompia o loop antes de instalar os runners. Agora
  `ws_data` é lido do `UserRole` do `ws_item` antes de chamar
  `_install_console_runner_children`.

## [0.21.1] — 2026-05-19

### Corrigido
- **Altura do botão 🗑 (remover runner)** (`ui/runner_widget.py`):
  o glyph 🗑 sozinho era renderizado com line-height maior que os
  botões irmãos, deixando o botão visivelmente mais alto. Agora a
  altura é fixada via `sizeHint()` do botão "Copiar log" pra alinhar
  com os demais.

### Adicionado
- **Botão "🧹 Limpar log"** no toolbar de cada runner: descarta o
  buffer de "Copiar log" e reseta o xterm.js (via novo sinal
  `clear_requested` no `TerminalBridge`). Útil pra limpar ruído de
  builds anteriores sem ter que reiniciar o processo.

## [0.21.0] — 2026-05-19

### Adicionado
- **Labels + badges no ActivityBar** (`ui/activity_bar.py`): cada entrada
  da coluna vertical de ícones (Workspaces / Catálogo / Hooks / MCP /
  Plugins / Apps / Settings) agora exibe ícone **+ label embaixo**, em
  vez de só o glyph. Antes só dava pra identificar via tooltip ao passar
  o mouse — agora é navegável de relance.
- **Contadores (badges) ao lado do ícone**: pequena pílula azul indica
  estado/quantidade do que está por trás de cada menu.
  - **Workspaces**: formato `trabalhando/total` (ex: `2/5`). Quando
    nada está rodando, mostra só o total. Tooltip detalha
    "N trabalhando · M ocioso(s) · T no total". Atualiza
    automaticamente em `refresh_list` e a cada
    `workspace_running_changed` (mesmo signal que já dirigia o spinner
    da sidebar).
  - **Apps auxiliares**: contagem de PWAs configurados em
    `settings.apps`. Atualiza ao salvar settings.
  - API genérica `activity_bar.set_badge(view_id, text, tooltip)` —
    outras views (catálogo/hooks/mcp/plugins) podem alimentar contagens
    no futuro sem mexer no widget.

### Alterado
- **Ícone de Workspaces**: trocado `❒` (quadrado vazio, pouco
  representativo) por `▦` (grade preenchida), evocando "vários projetos
  em tiles" — alinhado com a metáfora de workspaces múltiplos.
- **Largura do ActivityBar**: 48px → 68px pra comportar os labels sem
  truncar. Não afeta o splitter principal (a barra fica fora dele).
- **Botões viraram `QFrame` custom** (`_NavButton`) em vez de
  `QPushButton` — necessário pra layout vertical com ícone + label +
  badge na mesma linha do ícone. Exclusividade de seleção é gerenciada
  manualmente (substitui o `QButtonGroup`).

## [0.20.0] — 2026-05-18

### Performance
- **`git status` em 1 subprocess em vez de 4–5** (`git_status.py`):
  consolidado em `git status --porcelain=v2 --branch -z`, que devolve
  branch, ahead/behind e arquivos numa só chamada. Antes rodava
  `rev-parse --show-toplevel` + `rev-parse --abbrev-ref HEAD` +
  `rev-list --left-right --count` + `status --porcelain=v1` por pasta.
  Em workspaces com 10 pastas, reduz de ~50 forks de `git` por refresh
  pra 10. Parser dedicado de v2 (`_parse_porcelain_v2`) lida com
  records `1`/`2`/`?`/`u` e detached HEAD via `branch.oid`.
- **Diff de arquivo untracked grande não trava mais a UI**
  (`git_status.get_diff`): preview limitado a 512 KiB (`MAX_DIFF_BYTES`).
  Acima disso, mostra header + 512 KiB com prefixo `+`, em vez de
  carregar megabytes inteiros no `QPlainTextEdit`.
- **Highlight de diff via `QSyntaxHighlighter`** (`ui/git_panel.py`):
  antes um loop manual reformatava cada `QTextBlock` no `setPlainText`.
  Agora o Qt aplica formato apenas aos blocos afetados, virtualizado.
  Trocar de arquivo em diffs grandes ficou perceptivelmente mais
  responsivo.
- **Refresh do git panel pula rebuild quando estado não mudou**
  (`ui/git_panel.py`): cada `refresh()` agora calcula um fingerprint
  imutável do estado dos repos (branch, ahead/behind, lista de arquivos)
  e — se idêntico ao anterior e a árvore já existe — sai sem destruir e
  reconstruir os `QTreeWidgetItem`. Preserva scroll/seleção durante os
  polls de 30s quando nada mudou.
- **Cache de `git ls-files` no quick open** (`services/quick_open.py`):
  TTL de 5s por pasta. Antes cada keystroke disparava um subprocess
  `git ls-files` por pasta — com 5 pastas × 10 keystrokes eram 50 forks
  por busca. Agora a maioria dos keystrokes consecutivos reusa o
  resultado cacheado.
- **File finder roda busca em `QThreadPool`** (`ui/file_finder.py`):
  o walk (incluindo `git ls-files`/`fd`/fallback Python) saiu da thread
  de UI pra um `QRunnable`. Epoch counter descarta resultados obsoletos
  quando o usuário continua digitando. Cache de índice por folder
  (TTL 30s) elimina re-listagem entre keystrokes. Em repos com 10k+
  arquivos, primeiro keystroke deixa de bloquear a UI por ~1s.

## [0.19.2] — 2026-05-18

### Corrigido
- **Altura desproporcional do botão "Remover todos"**: o emoji 🗑
  forçava o QPushButton a crescer em altura por causa da métrica do
  glifo. Troca para `✕` (mesmo padrão dos outros botões como `■`/`▶`)
  pra manter a altura alinhada com o resto do header.
- **"Remover todos" agora lista os runners afetados e deixa explícito
  o escopo**: o diálogo de confirmação mostra os nomes que serão
  removidos e reforça que runners de outros escopos não são tocados.
  O laço de stop também passa a filtrar pelos ids in-scope, eliminando
  qualquer risco de parar runners fora do escopo.

## [0.19.1] — 2026-05-18

### Adicionado
- **Botão "📝 Editar script" no diálogo de edição do runner**: abre o
  arquivo de script referenciado pelo `start_cmd` no editor padrão do
  sistema. Detecta heuristicamente: `npm`/`yarn`/`pnpm`/`bun`/`npx` →
  `<cwd>/package.json`; `bash`/`sh`/`python`/`node`/etc + arquivo → o
  arquivo resolvido contra o cwd; caminho direto (ex.: `./run.sh`) →
  o próprio token. Quando nada é detectado, mostra mensagem explicando
  os formatos suportados. (O código já havia entrado em 0.19.0 junto
  com "Remover todos" mas ficou sem entrada no changelog.)

## [0.19.0] — 2026-05-18

### Adicionado
- **Botão "🗑 Remover todos" no header de runners**: remove de uma vez
  todos os runners do escopo atual (workspace ou console), com
  confirmação e contagem. Runners em execução são parados antes da
  remoção. Antes era preciso remover um por um pelo ícone de lixeira
  de cada aba.

## [0.18.11] — 2026-05-18

### Corrigido
- **"Runners workspace" volta para o topo do workspace na sidebar**:
  o group de runners workspace-scope agora é inserido em `index 0`
  do `ws_item` e os consoles entram via `addChild` no fim — ordem
  resultante: `Runners workspace → console1 → console2 → ...`.
  Antes (0.18.10) o group acabava no rodapé porque `_install_runner_children`
  usava `addChild` e o `_add_terminal_child` não compensava mais a posição.

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
