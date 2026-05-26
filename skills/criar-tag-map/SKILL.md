---
name: criar-tag-map
description: Cria uma tag git anotada no formato vX.Y.Z em AMBOS os repos do projeto MAP (map-api e map-web) usando a versao do package.json do map-web. A mensagem da tag vem do bloco da versao correspondente em release-notes-pt.json. Verifica que ambos os repos estao na mesma branch, que a branch esta sincronizada com o remote, e pusha as tags para origin apos confirmacao. Use quando o usuario pedir /criar-tag-map ou pedir explicitamente para criar/publicar tag de release do MAP.
---

# criar-tag-map

Creates an annotated git tag `vX.Y.Z` in BOTH MAP repos (`map-api` + `map-web`), using map-web's `package.json` version and the message from the matching block in `release-notes-pt.json`. Talk to the user in Portuguese.

## Flow

1. **Detect both repos:** cwd ends in `/map-api` or `/map-web`; the other is the sibling. `ls -d <other>/.git`; if missing, WARN and stop (both required). Use api first, then web.

2. **Version:** read `<REPO_WEB>/package.json`: `version` (`major.minor`, e.g. `"2.3"`) + `build` (`patch`, e.g. `"18"`). `TAG = "v"+version+"."+build` (e.g. `v2.3.18`). Missing/unexpected -> ABORT with the error.

3. **Branch:** `git rev-parse --abbrev-ref HEAD` in each. MANDATORY: BRANCH_API == BRANCH_WEB; if they differ, ABORT and show both. Present the branch and ASK explicit confirmation (user-facing message in pt-BR, e.g. "Voce esta em: <branch>... Confirma?"). If branch isn't `master` nor a known fix branch (`v2.2.0.12-correções`, `v2.3.x-correções_branch`), HIGHLIGHT the warning.

4. **Working tree:** per repo `git status --short`. Modified files other than the ignorable sensitive ones (`application-dev.yml`, `version.json`, `CLAUDE.md`) -> warn, ask abort/proceed.

5. **Synced with remote:** per repo, `git fetch origin "<BRANCH>"` then compare `git rev-parse HEAD` vs `origin/<BRANCH>`. MANDATORY: LOCAL == REMOTE in BOTH; else ABORT showing `git log origin/<BRANCH>..HEAD` (locais não pushados) and `HEAD..origin/<BRANCH>` (remotos não puxados). Tag must point to a published commit.

6. **Tag not existing:** per repo `git rev-parse --verify "<TAG>"` and `git ls-remote --tags origin "<TAG>"`. If it exists (local or remote) anywhere, ABORT — never overwrite.

7. **Message:** read `<REPO_WEB>/release-notes-pt.json`, find the block `"versao": "<version>.<build>"`. Not found -> ask abort or proceed with simple `Release <TAG>`. Found -> format multiline (omit empty sections):
   ```
   Release <TAG>
   Data: <data do bloco>

   Novidades:
   - <item>
   Bugs:
   - <item>
   ```

8. **Confirm plan** (TAG, BRANCH, commit hash/subject, the full tag message, both repo paths, "depois push origin nos dois"). Proceed only after "sim/ok/vai".

9. **Create** per repo, HEREDOC to preserve line breaks:
   ```bash
   cd "<repo>"
   git tag -a "<TAG>" -m "$(cat <<'EOF'
   <multi-line message from step 7>
   EOF
   )"
   ```
   Verify with `git tag -l "<TAG>"`.

10. **Push** per repo `git push origin "<TAG>"` (NEVER `--force`). Any failure -> STOP and report.

11. **Summary:** TAG, BRANCH, per repo (criada em <hash> | push OK/falha).

## Critical rules

- MANDATORY: both repos on the SAME branch name (else ABORT); branch synced with origin; tag must not already exist (never overwrite); format `vX.Y.Z` with `v`, always annotated (`-a -m`), never lightweight.
- ALWAYS confirm the branch and the full plan before creating/pushing. NEVER create without confirmation.
- NEVER `--force`/`--no-verify` or any destructive flag. NEVER modify working tree files (only creates a tag).
- Push only after the tag is created locally in both repos.
