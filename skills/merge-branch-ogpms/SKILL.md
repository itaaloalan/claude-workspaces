---
name: merge-branch-ogpms
description: Faz merge entre branches do projeto OGPMS seguindo operacoes fixas (develop -> homologacao_merge, develop -> 4 producao, homologacao_merge -> 4 homologacao) ou modo "Outros" (origem = branch atual, destino = develop ou homologacao_merge). Use ao pedir /merge-branch-ogpms ou explicitamente para fazer merge entre essas branches.
---

# merge-branch-ogpms

Merges between OGPMS's fixed branches. Branch names contain accents and `&` — ALWAYS quote them with double quotes in the shell. Talk to the user in Portuguese.

- **develop**, **homologação_merge**
- 4 Homologacao: `1_Homologação-Miranga`, `2_Homologação-PotiguarE&P`, `3_Homologação-Recôncavo`, `4_Homologação-Tieta`
- 4 Producao: `1_Produção-Miranga`, `2_Produção-PotiguarE&P`, `3_Produção-Recôncavo`, `4_Produção-Tieta`

## Operation mapping

| Option | Source | Destinations |
|-------|--------|----------|
| 1 | `develop` | `homologação_merge` |
| 2 | `develop` | the 4 `*_Produção-*` |
| 3 | `homologação_merge` | the 4 `*_Homologação-*` |
| 4 (Outros) | current branch | `develop` OR `homologação_merge` (ask) |

## Flow

1. **State:** `git status --short`. If there are relevant changes, ask: abort / stash / proceed (only with confirmation). Always ignorable in this check: `glassfish-resources.xml`, `CLAUDE.md`. Capture the current branch (`git rev-parse --abbrev-ref HEAD`) — it's the SOURCE_ORIGINAL to return to at the end.

2. **Operation:** `AskUserQuestion` (header "Operacao") with the 4 options above.

3. **If "Outros":** SOURCE = current branch. If SOURCE is `develop`/`homologação_merge`, warn (may be a mistake). Second `AskUserQuestion` for the destination (`develop` or `homologação_merge`) — respecting the FORBIDDEN rule below.

4. **Confirm the plan** in text (source, destinations, "for each: checkout, pull --ff-only, merge --no-ff, push; at the end return to original"). Only proceed with explicit confirmation.

5. **Execute.** Before switching branches, stash the local config:
   `git stash push -u -- src/main/webapp/WEB-INF/glassfish-resources.xml CLAUDE.md` (pop when returning).
   For each destination, in order:
   1. `git checkout "<DEST>"` (quotes!)
   2. `git pull --ff-only`
   3. `git merge --no-ff "<SOURCE>" -m "merge: <SOURCE> -> <DEST>"`
   4. Conflict? STOP, show `git status` + files, do NOT continue to other destinations, ask how to proceed.
   5. `git push` (never `--force`)
   6. Log `[OK] <SOURCE> -> <DEST>`.
   Any failure (diverged, push rejected): STOP and report, don't force.

6. **Return:** `git checkout "<SOURCE_ORIGINAL>"` and pop the stash.

7. **Summary** with per-destination status ([OK]/[FALHA]/[PENDENTE]) and the branch returned to.

## Critical rules

- **FORBIDDEN:** NEVER merge `homologação_merge` -> `develop`, nor `homologação_merge` -> any Producao. The flow only goes develop->homologação_merge->4 Homologacao, or develop->4 Producao. If "Outros" tries this, BLOCK and explain — not even with confirmation.
- **CRITICAL:** `glassfish-resources.xml` (local DB config) must NEVER change on the other branches. If a merge brings a change to it, STOP and alert — likely an accidental commit; do NOT commit, do NOT push. That's why step 5 stashes it.
- NEVER `--force`/`--force-with-lease`/`-f`/`--no-verify`, nor `reset --hard`/`checkout -- .`/`clean -f`.
- ALWAYS `--ff-only` on the destination pull (never `--rebase`), `--no-ff` on the merge, double quotes on names.
- A conflict is never resolved alone — stop and ask. Push only after a successful merge.
