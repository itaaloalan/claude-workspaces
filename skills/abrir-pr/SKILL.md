---
name: abrir-pr
description: Abre um Pull Request no GitHub para a branch atual usando gh CLI. Analisa os commits da branch, sugere titulo e corpo em Conventional Commits/portugues, confirma com o usuario antes de criar, faz push se necessario e retorna a URL. Use quando o usuario pedir para abrir PR, criar PR, criar pull request, ou /abrir-pr.
---

# abrir-pr

Creates a GitHub PR via `gh` CLI, with title/body generated from the current branch's commits. Talk to the user in Portuguese.

**Prereqs:** `gh` authenticated (`gh auth status` — if not, tell the user to run `gh auth login` and stop); current branch NOT `main`/`master` (ask first if it is); `origin` on GitHub.

## Flow

1. **Context:**
   ```bash
   git branch --show-current
   git log --oneline origin/main..HEAD      # commits (ou origin/master)
   git diff --stat origin/main...HEAD       # resumo do diff
   gh pr view --json url,state 2>/dev/null   # PR ja existe?
   ```
   If an open PR exists for the branch, show the URL and ask: update it (`gh pr edit`) or open a new one (rare — abort by default).

2. **Base branch:** default `main`; auto-detect via `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`. If the branch wasn't cut from base (`git merge-base`), warn. If undetected, ask.

3. **Title + body:** title (max 72c) = last commit if a single relevant one, else synthesize in Conventional Commits (pt). Body:
   ```
   ## Resumo
   <2-4 bullets: o que mudou e por que>
   ## Mudancas
   <arquivos/areas, agrupados por camada (API, web, app, testes)>
   ## Como testar
   <passos curtos pra validar localmente>
   ```
   NEVER include "Co-Authored-By: Claude" or any AI reference. Show to the user, allow edits, confirm.

4. **Pre-flight (MANDATORY if repo has web/api)** — avoid pipeline failures:
   - web: `cd <repo>/src/web && pnpm build` — fail -> show error and STOP (no push/PR).
   - .NET: `cd <repo>/src/api && dotnet test --nologo` — any failure -> show which and STOP.
   - No `src/web`/`src/api`: adapt or skip, warning the user.
   - Mobile app (`src/app`): do NOT build (`expo` is slow, needs device) — skip.
   - Sonar: do NOT run locally (no in-process analyzers); CI handles it per-PR.

5. **Push if needed** (no upstream or behind): `git push -u origin <branch>`. Never `--force`/`--force-with-lease` unless explicitly asked.

6. **Create:** HEREDOC for the body:
   ```bash
   gh pr create --base main --head <branch> --title "<titulo>" --body "$(cat <<'EOF'
   <corpo>
   EOF
   )"
   ```
   Capture the URL.

7. **Report:** PR URL, commit count, warn about uncommitted files left out of the PR.

## Rules

- NEVER commit automatically (assume the user committed what they wanted). NEVER `push --force`.
- Uncommitted changes: warn but don't block (may be intentional).
- Monorepo with multiple .git: operate in the current directory (don't guess).
