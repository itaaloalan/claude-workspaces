---
name: orval-web
description: Regera os clientes Orval do projeto SIPE web (sipe + manager) consumindo o swagger da API local. Use quando o usuario pedir para rodar orval do web, regerar clientes web, sincronizar tipos do web com o backend, ou /orval-web.
---

# Skill: orval-web

Talk to the user in Portuguese.

Regenerates the **SIPE web** clients (`src/web`) via Orval. Two targets in `src/web/orval.config.ts`: `sipe` (`:5000`) and `manager` (`:5001`).

## Execution

```bash
# 1. Check APIs
curl -fs -o /dev/null -w "sipe=%{http_code} " --max-time 3 http://localhost:5000/swagger/v1/swagger.json
curl -fs -o /dev/null -w "manager=%{http_code}\n" --max-time 3 http://localhost:5001/swagger/public/swagger.json

# 2. Run (from src/web)
pnpm orval                       # both
pnpm orval --project sipe        # sipe only (use if manager is down)
pnpm orval --project manager     # manager only

# 3. Refresh git cache (clears mtime "ghosts")
git update-index --refresh > /dev/null 2>&1 || true
comm -23 <(git ls-files -m src/web/ | sort) <(git diff --name-only src/web/ | sort) | xargs -d '\n' -r git checkout HEAD --

# 4. Report
echo "M: $(git diff --name-only src/web/ | wc -l) | D: $(git ls-files --deleted src/web/ | wc -l) | ??: $(git ls-files --others --exclude-standard src/web/ | wc -l)"
```

## Rules

- If any API is down (HTTP != 200), warn before running and ask whether to start it or skip that target.
- Do NOT commit. Only generate and report the diff.
- Large drift (>50 files) = accumulated debt (someone changed the backend without regenerating). Suggest `chore: regenerate orval clients`.
- `clean: true` is active on both targets — it wipes and regenerates everything. Do NOT try to preserve files manually.
