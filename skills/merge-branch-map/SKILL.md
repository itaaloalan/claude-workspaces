---
name: merge-branch-map
description: Faz merge entre branches do projeto MAP — opera SEMPRE nos DOIS repos (map-api e map-web) em sequencia, com a mesma operacao em cada. Fluxos suportados - branches de correcao (v2.2.0.12-correções, v2.3.x-correções_branch, etc) sobem para master e/ou dev; master sobe rotineiramente para dev; qualquer outra branch (feature/bugfix) sobe para dev. NUNCA faz dev -> master (dev sempre tem coisas que nao podem ir pra master). Branches de cliente (Produção/*) NAO sao escopo desta skill. Use quando o usuario pedir /merge-branch-map ou pedir explicitamente para fazer merge entre branches do MAP.
---

# merge-branch-map

Merges between MAP branches, ALWAYS on BOTH repos (`map-api` then `map-web`), same operation each. Branch names are identical in both and contain `ç`/`ã` — ALWAYS double-quote them in the shell. Talk to the user in Portuguese.

**Branches:** `master` (production, only receives fix branches), `dev` (receives master, fixes, features/bugfixes). Fix branches (`v2.2.0.12-correções`, `v2.3.x-correções_branch`, or future ones) go to master and/or dev. Any other branch goes only to dev. `Produção/*` (client) are OUT of scope.

## Flow

1. **Detect both repos:** cwd ends in `/map-api` or `/map-web`; the other is the sibling. `ls -d <other>/.git` to confirm; if missing, warn and ask whether to proceed with only one. Order = REPO_API then REPO_WEB.

2. **State of BOTH:** per repo `git status --short` + current branch; show a compact table. Sensitive files always ignorable (and stashed before first checkout): `src/main/resources/application-dev.yml` (api), `src/assets/version.json` (web), `CLAUDE.md`. Other relevant changes -> ask abort/stash/proceed. Capture each repo's original branch to return to.

3. **Operation** (`AskUserQuestion`, once for both): 1) master→dev; 2) `<correcao>`→master; 3) `<correcao>`→dev; 4) Outros (current branch→dev). NEVER offer `dev→master` nor any `Produção/*` — if asked, BLOCK and explain.

4. **Option 2/3:** ask SOURCE (`AskUserQuestion`: list known fix branches + free field). New branch -> verify it exists in BOTH (`git rev-parse --verify`); missing in one, warn which and ask. DEST = master (opt 2) or dev (opt 3).

5. **Option 4:** SOURCE = cwd's current branch. BLOCK if SOURCE is `master` (use opt 1), `dev` (no sense), or `Produção/*`. If SOURCE is a known fix branch, warn there's a clearer option (3). DEST = dev. In the other repo verify SOURCE exists; if not, ask skip-that-repo or another name.

6. **Confirm plan** (source, dest, the per-repo steps below, both repo paths). Proceed only after explicit "sim/ok/vai".

7. **Execute per repo (api then web)** — each independent; if one fails still try the other:
   1. **Stash** (before first checkout) if any sensitive file is dirty — single `git stash push -u -m "merge-branch-map: arquivos locais" -- <os arquivos sensiveis do repo>`; ignore files absent in the repo. Record if stashed.
   2. **Pull:** `git checkout "<SOURCE>" && git pull --ff-only`; then `git checkout "<DEST>" && git pull --ff-only`. Divergence on DEST -> STOP that repo as FALHA, go to next repo.
   3. **Merge:** `git merge --no-ff "<SOURCE>" -m "merge: <SOURCE> -> <DEST>"`.
   4. **Conflicts:** resolve only when obvious (import unions, independent blocks); then `git add` + `git commit --no-edit`. Non-trivial -> STOP that repo, show files, ask. Can't resolve safely -> `git merge --abort`, mark CONFLITO_PENDENTE, next repo.
   5. **Sensitive check:** `git show --name-only HEAD`; if a sensitive file (`application-dev.yml`, `version.json`) appears, STOP that repo (likely leaked local config), do NOT push, mark PRECISA_REVISAO, next repo.
   6. **Push:** `git push` (NEVER `--force`/`--force-with-lease`). DEST `master` is the most sensitive — confirm ONCE before the first master-destination repo, applies to both. `dev` pushes directly (plan already confirmed).
   7. **Return:** `git checkout "<branch original do repo>"` and `git stash pop` if stashed (pop conflict -> alert, keep stash).

8. **Summary** per repo: status ([OK]/[FALHA]/[CONFLITO_PENDENTE]/[PRECISA_REVISAO]) + commit, push (feito/pendente/n-a), branch de retorno, stash pop.

## Option mapping

| Opcao | Source | Destino | Repos |
|-------|--------|---------|-------|
| 1 | `master` | `dev` | api+web |
| 2 | fix branch (lista+outra) | `master` | api+web |
| 3 | fix branch (lista+outra) | `dev` | api+web |
| 4 | branch atual do cwd | `dev` (com bloqueios) | api+web (se SOURCE existir) |

## Critical rules

- ALWAYS operate on BOTH repos in sequence (api then web); each independent.
- FORBIDDEN: `dev→master` (dev always has work that can't go to master) — never offered/executed, even via Outros; BLOCK and explain. FORBIDDEN: merge to OR from any `Produção/*`.
- CRITICAL: `application-dev.yml` (api) and `version.json` (web) must NEVER change on other branches. If a merge brings changes to either, STOP that repo and alert — likely accidental commit to revert at source; do NOT push. Continue with the other repo if OK.
- ALWAYS stash sensitive files before the first checkout of each repo and pop at the end.
- ALWAYS confirm before pushing to `master` (one confirmation for both repos).
- NEVER `--force`/`--force-with-lease`/`-f`/`--no-verify`, nor `reset --hard`/`checkout -- .`/`clean -f`. NEVER `pull --rebase` — always `--ff-only` for DEST. ALWAYS `--no-ff` on merge and double quotes on names.
