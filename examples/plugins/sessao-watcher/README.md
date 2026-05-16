# Sessão Watcher

Plugin de exemplo do Claude Workspaces. Observa eventos de mudança de status
de sessão e notifica o usuário quando alguma fica aguardando input por mais
tempo do que o configurado, evitando que sessões fiquem esquecidas no
inbox por horas.

## Permissões pedidas

- `notifications: true` — pra exibir notificação quando o limiar é atingido.
- `workspaces: all` — observamos sessões de qualquer workspace; sem listas
  fixas. Não há leitura ou escrita de filesystem nem acesso à rede.

## Configurações disponíveis

- `threshold_minutes` (integer, default 5) — tempo mínimo (em minutos) que
  uma sessão precisa ficar em `awaiting-input` antes de virar notificação.
  Faixa permitida: 1 a 60.

## Exemplo de uso

Depois de instalar (Plugins → Instalar de pasta → escolher `examples/plugins/sessao-watcher`),
abra qualquer console do Claude e deixe-o aguardando input. Após o número de
minutos configurado, uma notificação do sistema avisa que a sessão está
parada — incluindo o nome do workspace e o último título.

Útil pra quem mantém múltiplos consoles em paralelo e às vezes esquece um
console aberto numa pergunta.
