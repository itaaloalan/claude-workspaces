# Commit Coach

Plugin de exemplo do Claude Workspaces. Avalia toda mensagem nova de commit
e mostra um toast quando algo destoa do padrão — sem bloquear o commit, só
sinalizando para o autor revisar.

## O que ele checa

- **Conventional Commits**: a 1ª linha precisa começar com `tipo[(escopo)]: assunto`,
  e o `tipo` precisa estar na lista canônica (`feat`, `fix`, `docs`, `style`,
  `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `merge`).
- **Tamanho do assunto**: avisa se a 1ª linha passar do limite configurado
  (default 72 caracteres).
- **Marcas de WIP**: detecta `wip`, `tmp`, `fixme`, `todo`, `xxx` no assunto
  e sugere revisar antes de subir.

## Permissões pedidas

- `notifications: true` — para exibir toast quando algo destoa.
- `workspaces: all` — escuta commits de qualquer workspace.

Nada de filesystem, nada de rede.

## Configurações

| Chave | Tipo | Default | O que faz |
|---|---|---|---|
| `enforce_conventional` | boolean | `true` | Liga/desliga a checagem de Conventional Commits |
| `max_subject_length` | integer | `72` (30–120) | Limite do tamanho da 1ª linha |
| `warn_on_wip` | boolean | `true` | Liga/desliga o aviso de mensagens com cara de WIP |

## Exemplo de uso

Instale o bundle (Plugins → Instalar de pasta → `examples/plugins/commit-coach`)
e faça um commit qualquer. Quando a mensagem fugir do padrão, um toast
aparece no canto da janela com o resumo do problema.
