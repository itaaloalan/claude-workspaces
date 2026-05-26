---
name: gerar-release-map
description: Especifica para o projeto MAP (map-web). Atualiza release-notes-pt.json, release-notes-en.json e package.json com novas entradas de bugs/novidades, traduz pt->en automaticamente, e permite anexar a versao atual ou criar nova versao com bump. Use ao pedir para atualizar release notes do MAP, bumpar versao, ou /gerar-release-map.
---

# gerar-release-map

Updates the MAP release notes (`release-notes-pt.json`, `release-notes-en.json`) and, on a bump, `package.json`. Accepts multiple entries per run and translates pt->en. Talk to the user in Portuguese.

## Steps (in order)

1. **Locate** the 3 files at the project root (cwd + additional working dirs). If any is missing, warn and stop — do not create files.

2. **Show current state** (compact): `package.json` version, version+date at the top of `release-notes-pt.json` and `-en.json`.
   - MAP uses TWO fields in `package.json`: `version` = `major.minor` (e.g. `"2.3"`), `build` = `patch` as a string (e.g. `"16"`). Together = `2.3.16`.

3. **Decide target version:**
   - **(a) Append to the top version** — keeps the current date, does NOT touch `package.json`.
   - **(b) Bump** — ask which: patch (`X.Y.Z`->`X.Y.Z+1`), minor (`->X.(Y+1).0`), major (`->(X+1).0.0`), or a custom version.
   - On bump, compute today's date (pt `DD/MM/AAAA`, en `MM/DD/AAAA`) and confirm with the user.

4. **Collect entries** (loop): for each one, category (`bugs`|`novidades`) + pt text in the style of the existing ones. Accept several in a row; stop when the user says "ok/pronto/fim". If this session's diff already makes clear what changed, propose pre-filled entries and just ask for confirmation.

5. **Translate pt->en** in the style of `release-notes-en.json` (read previous entries to calibrate tone). Terms: alarme->alarm, alerta->alert, supervisao->supervision, poco->well, configuracao->settings/configuration. Bugs start with "Fix in/when..." or "Adjustment of..."; novidades with "Implementation/Standardization/Addition of...". Show pt+en side by side and ask whether to adjust.

6. **Preview** the changes (target version, dates, package.json fields if bump, entries per file) and ask for final confirmation.

7. **Apply** (via Edit):
   - Update both JSON files. New version = first item of the `versoes` array; append = at the end of the current block's `bugs`/`novidades` arrays.
   - On bump, update `package.json`: **patch** changes only `build` (`version` stays); **minor/major** change `version` to the new `major.minor` and reset `build` to `"0"`. Append doesn't touch it.
   - Strict JSON: preserve indentation (4 spaces), double quotes, and mind commas (last array item has no trailing comma).

8. **Build:** run `npm run prod` at the map-web root, in background (`run_in_background: true`), and tell the user it's running. If it fails, report the error (don't try to fix it). Skip if the user asks.

9. **Post:** list the 3 changed files, build status, suggest reviewing `git diff`. Commit is NOT done — suggest `/commit-arquivo`.

## Critical rules

- NEVER edit files other than the 3. NEVER delete entries from previous versions. NEVER run `git add`/`commit`.
- ALWAYS show the preview before saving and confirm version+date.
- ALWAYS run `npm run prod` after editing, unless asked to skip.
