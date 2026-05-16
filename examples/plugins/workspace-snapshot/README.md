# Workspace Snapshot

Plugin de exemplo do Claude Workspaces. Tira um snapshot quando você
**abre** um workspace e gera um resumo quando você **fecha** — mostrando
quanto tempo ficou aberto, quantas sessões foram criadas e quantos commits
saíram durante a janela.

É um "ata de reunião" automático pra cada sessão de trabalho.

## Como funciona

Cada workspace tem uma "janela atual" no `ctx.storage`:

- **workspace.opened** zera a janela e marca o timestamp inicial.
- **session.created** + **commit.created** filtram por `workspace_id` e
  incrementam contadores quando o workspace está aberto.
- **workspace.closed** lê a janela, calcula a duração e dispara uma
  notificação (se passou do mínimo configurado), depois apaga a janela.

Se o workspace fechar antes do mínimo (`min_duration_seconds`), a janela
é descartada sem notificação — evita poluir a tela com "passei 2s aqui".

## Permissões pedidas

- `notifications: true` — para o resumo final.
- `workspaces: all` — escuta eventos de qualquer workspace.

Nada de filesystem, nada de rede. Só estado interno em `ctx.storage`,
isolado por plugin.

## Configurações

| Chave | Tipo | Default | O que faz |
|---|---|---|---|
| `notify_on_close` | boolean | `true` | Liga/desliga a notificação final |
| `min_duration_seconds` | integer (0–3600) | `30` | Duração mínima da janela para gerar resumo |

## Exemplo de notificação

> **Snapshot — meu-projeto**
> Duração: 47min
> Sessões abertas: 3
> Commits: 2

Workspaces fechados sem sessões nem commits aparecem com "Sem sessões nem
commits durante a janela." — útil pra perceber quando uma janela passou
em branco.
