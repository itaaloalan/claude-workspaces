# Idle Rescue

Plugin de exemplo do Claude Workspaces. Quando uma sessão fica em
`awaiting-input` por mais tempo do que o configurado, mostra uma notificação
com **um trecho da última mensagem** e uma **sugestão de prompt** pra retomar
o trabalho — ajuda a destravar sessões que ficaram penduradas numa pergunta.

É complementar ao `sessao-watcher`: aquele só avisa; este sugere o próximo passo.

## Permissões pedidas

- `notifications: true` — para a sugestão chegar pelo sistema.
- `workspaces: all` — observa sessões de qualquer workspace.

Nada de filesystem, nada de rede.

## Configurações

| Chave | Tipo | Default | O que faz |
|---|---|---|---|
| `idle_threshold_minutes` | integer (1–120) | `10` | Tempo mínimo em awaiting-input antes do nudge |
| `nudge_style` | enum: gentil / direto / tecnico | `gentil` | Tom da mensagem de retomada |
| `include_last_message` | boolean | `true` | Inclui o trecho da última mensagem da sessão |

## Exemplo de uso

Após instalar, qualquer sessão que estiver aguardando input por mais que
`idle_threshold_minutes` recebe uma notificação como:

> **Bora retomar?**
> [meu-projeto]
> Último: implementar parser do…
> Tente: "continua daí com calma, e me avisa se precisar de contexto"

Trocando o `nudge_style` o tom muda — útil pra quem prefere uma sugestão
mais seca ou mais técnica.
