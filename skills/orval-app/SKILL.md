---
name: orval-app
description: Regera o cliente Orval do projeto SIPE app mobile (Expo/React Native) consumindo o swagger da API local. Use quando o usuario pedir para rodar orval do app, regerar clientes do app mobile, sincronizar tipos do app com o backend, ou /orval-app.
---

# Skill: orval-app

Talk to the user in Portuguese.

Regenerates the **SIPE app mobile** client (`src/app`, Expo/React Native) via Orval. A single target in `src/app/orval.config.ts`: `sipe` (`:5000`). The orval version in the app is `v7.x` (intentional, do NOT try to upgrade it).

## Execution

```bash
# 1. Check API
curl -fs -o /dev/null -w "sipe=%{http_code}\n" --max-time 3 http://localhost:5000/swagger/v1/swagger.json

# 2. Run (from src/app)
pnpm orval

# 3. Refresh git cache (clears mtime "ghosts")
git update-index --refresh > /dev/null 2>&1 || true
comm -23 <(git ls-files -m src/app/ | sort) <(git diff --name-only src/app/ | sort) | xargs -d '\n' -r git checkout HEAD --

# 4. Report
echo "M: $(git diff --name-only src/app/ | wc -l) | D: $(git ls-files --deleted src/app/ | wc -l) | ??: $(git ls-files --others --exclude-standard src/app/ | wc -l)"
git log -1 --format="ultima regen: %ai" -- src/app/api/
```

## Rules

- If the API is down (HTTP != 200), warn before running.
- Do NOT commit. Only generate and report the diff.
- Large drift (>50 files) = accumulated debt. Check `git log -1 -- src/app/api/`: if it is old (weeks+), suggest `chore: regenerate orval clients (app)` in a separate commit.
- `clean: true` is active — it wipes and regenerates everything. Do NOT try to preserve files manually.
