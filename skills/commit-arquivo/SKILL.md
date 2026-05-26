---
name: commit-arquivo
description: Faz commit seletivo dos arquivos modificados pelo usuario, com analise de codigo e sugestoes antes do commit. Ignora arquivos especificos (como glassfish-resources.xml). Usa Conventional Commits (feat:, fix:, etc.) em portugues, sem referencia ao Claude. Use ao pedir para commitar mudancas, fazer um commit, ou /commit-arquivo.
---

# commit-arquivo

Selective commit of the user's modified files, with code review first. All user-facing output (questions, summaries) and the commit message itself are in **Portuguese (pt-BR)**. Follow the steps in order.

1. **List:** `git status --short`. Present numbered, grouped: modified (M), new (??), deleted (D).

2. **Filter ignored** (keep in working tree, do NOT `restore`/`checkout`):
   - Always: `src/main/webapp/WEB-INF/glassfish-resources.xml`.
   - Anything that looks like local config/credentials (`.env`, `*.local.xml`, files with passwords): warn and confirm.
   - Ask whether there's anything else to exclude from this commit.

3. **Diff:** for each file to be committed, `git diff <file>` (or `--cached`, or show content if new). Summarize the changes.

4. **Review** for: logic/bugs (inverted condition, off-by-one, NPE, resource leak), security (SQLi, XSS, hardcoded credentials, logging sensitive data), encoding in `.java` files (CLAUDE.md requires Windows-1252), dead/commented code, project conventions, performance (N+1, loops), maintainability.

5. **Doubts and suggestions:** if you have ANY doubt about intent, ASK first. Classify suggestions as critical / recommended / observations and ask whether to apply before committing.

6. **Message** — Conventional Commits in Portuguese (`feat/fix/refactor/style/docs/test/chore/perf`):
   - Max 72 chars on the first line; focus on the **why**; TITLE ONLY by default (body only if the user asks or for a large change >5 related files).
   - NEVER include Co-Authored-By or any AI signature.
   - Multiple distinct changes -> suggest separate commits.
   - Show the message in a code block, nothing extra inside it. Review context goes OUTSIDE the block. Confirm before proceeding.

7. **Stage + commit** (after confirmation):
   - `git add <specific files>` — NEVER `git add .` or `-A`.
   - `git status` to verify the stage.
   - commit via heredoc: `git commit -m "$(cat <<'EOF'` ... `EOF` `)"`.
   - `git status` to confirm.

8. **Post:** `git log -1 --oneline`, list what stayed out of the commit. Do NOT push.

## Critical rules

- NEVER: `--no-verify`, `--amend` (unless explicitly requested), `git restore`/`checkout --`/`reset --hard` or anything destructive, AI signature.
- ALWAYS: ask if in doubt; list the `add` files explicitly (no wildcards). Ignored files stay in the working tree.
