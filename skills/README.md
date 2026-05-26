# Skills (snapshot versionado)

Cópia versionada das skills custom que vivem em `~/.claude/skills`. Serve de
backup e histórico — **não é a cópia que o Claude Code executa**. A que roda
continua sendo a de `~/.claude/skills`.

## Regra de sincronização

Como é snapshot (cópia, não symlink), as duas cópias **podem divergir**. Sempre
que uma skill em `~/.claude/skills` for criada ou ajustada, re-sincronizar aqui:

```bash
cp -a ~/.claude/skills/. skills/
```

E ao restaurar numa máquina nova, o caminho inverso:

```bash
cp -a skills/. ~/.claude/skills/
```

## Formato das skills

- `description` em PT (gatilhos em português), body em inglês, literais pt-BR.
- Respeitar `src/claude_workspaces/skills_lint.py` (description 30–1000 chars,
  body ≥ 50 chars, `name` igual ao nome da pasta).
