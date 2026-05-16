# Focus Timer

Plugin de exemplo do Claude Workspaces. Acumula quanto tempo as sessões
passaram em cada status durante o dia (running / awaiting-input / idle) e
expõe dois comandos na paleta (Ctrl+P) pra ver o resumo ou zerar a contagem.

Funciona como um "diário leve" do seu uso: no fim do dia, você dispara
**Focus: resumo de hoje** e recebe um cartão com os totais.

## Permissões pedidas

- `notifications: true` — para o resumo aparecer.
- `workspaces: all` — agrega tempo de qualquer workspace.

Nada de filesystem, nada de rede. Os contadores ficam em `ctx.storage`
(isolado por plugin).

## Como o tempo é contabilizado

Cada `session.status-changed` traz o status anterior e a duração nele;
somamos isso em `day:<YYYY-MM-DD>:<status>_ms`. O totalizador `idle`
só conta quando você liga `count_idle_as_focus` — por default, idle não
vira foco (ficar com a janela aberta sem mandar nada não é trabalho).

`session.completed` incrementa `completed_count` e `completed_total_ms`.

## Comandos (Ctrl+P)

| Comando | O que faz |
|---|---|
| **Focus: resumo de hoje** | Notificação com running / aguardando / idle / sessões concluídas |
| **Focus: zerar contadores de hoje** | Apaga só as chaves do dia atual; histórico antigo permanece |

## Configurações

| Chave | Tipo | Default | O que faz |
|---|---|---|---|
| `count_idle_as_focus` | boolean | `false` | Inclui status idle no totalizador |

## Limitações conhecidas

- O dia é UTC (não local) — útil para consistência entre dispositivos, mas
  pode dar resultado contraintuitivo em fusos longe de UTC.
- Não há rotação automática de histórico: chaves de dias antigos ficam no
  storage. Se incomodar, dá pra estender com um comando "limpar histórico".
