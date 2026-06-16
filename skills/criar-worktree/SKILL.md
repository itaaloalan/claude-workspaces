---
name: criar-worktree
description: "✍️ Criado por mim: Cria branch + worktree em qualquer repo git, sempre perguntando qual branch base usar (dev/develop/main/master ou a branch atual). Branch segue prefixos convencionais (feat/, fix/, chore/, refactor/...). Worktree individual em <repo>.claude/<ws>_<type>_<nome>; multi-repo usa pasta-pai (<WS_ROOT>/.worktrees/<type>_<nome>/<repo>), abrível via 'Abrir console no grupo'. Copia CLAUDE.md/.env e sincroniza banco pelo MCP. Remove worktrees com /criar-worktree remover. Usar ao pedir /criar-worktree, criar worktree, criar branch com worktree, ou remover worktrees."
---

# criar-worktree

Creates a new branch + worktree in any git project. Always asks which base branch to use — never assumes a default. Also removes worktrees on request.

**Language:** Portuguese (pt-BR) for all user-facing text — questions, warnings, summaries. Branch names: kebab/snake slug, no accents, no spaces.

**Mode selection:** if the user asked to remove/clean (`/criar-worktree remover`, "remova o worktree", "limpa os worktrees") → **Removal mode**. Otherwise → **Creation flow**.

---

## Creation flow

### Step 1 — Parallel discovery

Emit these as **separate parallel Bash calls** (all independent, all read-only):

```bash
# Call A
git rev-parse --show-toplevel 2>/dev/null || echo NOT_A_REPO
# Call B
git rev-parse --abbrev-ref HEAD
# Call C
for b in dev develop main master; do
  if git show-ref --verify -q "refs/heads/$b" || git show-ref --verify -q "refs/remotes/origin/$b"; then echo "$b"; fi
done
# Call D
cat ~/.config/claude-workspaces/workspaces.json 2>/dev/null || echo '{}'
# Call E
git remote get-url origin 2>/dev/null || echo NO_REMOTE
```

Derive from results:
- `REPO`: the toplevel path. If `NOT_A_REPO`, stop and tell the user.
- `CURRENT_BRANCH`: currently checked-out branch.
- `CONVENTIONAL`: list of dev/develop/main/master found locally or on remote.
- `WS` + `FOLDERS`: from workspaces.json, find the entry whose `folders` contains `REPO`. `WS` = workspace name; `FOLDERS` = its folder list. Fallback: `WS` = `basename(REPO)`, `FOLDERS` = [`REPO`].
- `HAS_REMOTE`: whether origin exists.

### Step 2 — One AskUserQuestion (all needed questions)

Ask ALL needed questions in a **single `AskUserQuestion` call** (up to 4 questions). Include only what is actually needed:

**Q1 (always): Base branch.**
- If `CURRENT_BRANCH` is NOT in `CONVENTIONAL`, put it first (Recommended) — the user is likely working off it.
- Otherwise put the top conventional branch first (Recommended, priority: dev > develop > main > master).
- Include remaining conventional branches as options. User can always type Other (handles accents/`&`).
- Show whether each option exists on the remote and is in sync, when useful.
- If NO conventional branches exist AND there is no usable current branch, stop and warn.

**Q2 (only if `FOLDERS` has 2+ entries): Which repos to create the worktree in.** multiSelect; list all folders as options. Use project memory to pre-select the relevant default (e.g. MAP: map-api + map-web). 1 selected → single-repo mode; 2+ → multi-repo mode.

**Q3 (only if branch type is NOT determinable from the user's request): Branch type.** Options: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`.

> Branch NAME (slug) is derived from the user's task description — no need to ask. State the intended slug in the question text so the user can select Other to override.

### Step 3 — Resolve paths + existence checks + fetch

After the user answers, compute:

- `BRANCH`: `<type>/<name>` (no accents, kebab slug).
- `WT_PATH`:
  - **Single-repo:** `<REPO>.claude/<WS>_<type>_<name>` (e.g. `/path/ogpms.claude/ogpms_feat_api_xml`)
  - **Multi-repo:** for each selected repo → `<WS_ROOT>/.worktrees/<type>_<name>/<repo-basename>`, where `WS_ROOT` = `os.path.commonpath(selected_repos)`.

**Existence checks — ONE Bash call, both checks:**
```bash
{ test -d "<WT_PATH>" && echo WT_EXISTS; }; { git show-ref --verify -q "refs/heads/<BRANCH>" && echo BRANCH_EXISTS; }
```
If either exists, STOP and report. Never `--force` on creation.

**Fetch base (if `HAS_REMOTE`):**
```bash
git fetch origin "<BASE>"
```
Prefer `origin/<BASE>` as the start point in Step 4; fall back to local `<BASE>` if `origin/<BASE>` doesn't exist.

### Step 4 — Create (literal paths, each as own Bash call)

**NEVER use shell variables** (`$WT`, `$BR`) or `if/elif` wrappers for paths/branches. The claude-workspaces app parses `git worktree add` from the session JSONL (`scan_worktree_adds`) statically — `$WT` is parsed as the literal string `"$WT"`, fails validation, and the 🌿 badge never appears.

**Single-repo (one Bash call):**
```bash
git worktree add "<REPO>.claude/<WS>_<type>_<name>" -b "<type>/<name>" "origin/<BASE>"
```

**Multi-repo:** first `mkdir -p "<WS_ROOT>/.worktrees/<type>_<name>"`, then one Bash call per repo (the `-C` flag is parsed correctly by `scan_worktree_adds`):
```bash
git -C "<REPO_A>" worktree add "<WS_ROOT>/.worktrees/<type>_<name>/<REPO_A_BASENAME>" -b "<type>/<name>" "origin/<BASE>"
git -C "<REPO_B>" worktree add "<WS_ROOT>/.worktrees/<type>_<name>/<REPO_B_BASENAME>" -b "<type>/<name>" "origin/<BASE>"
```

### Step 5 — Move cwd into the worktree

Run as its own Bash call (cwd persists between calls, so subsequent commands start in the worktree automatically):
- Single-repo: `cd "<REPO>.claude/<WS>_<type>_<name>"`
- Multi-repo: `cd "<WS_ROOT>/.worktrees/<type>_<name>/<primary-repo-basename>"`

Skip silently only if creation failed.

### Step 6 — Copy Claude-local files

Copy only if the file exists in `REPO` and is untracked or locally modified:
- `CLAUDE.md` (if untracked)
- `.claude/settings.local.json`
- `.env`, `.env.local` (if untracked)
- Project-known local configs with uncommitted changes (e.g. `src/main/webapp/WEB-INF/glassfish-resources.xml`): copy the working-tree version over the worktree's checked-out file.

List what was copied.

### Step 7 — Sync DB config from the project MCP

The worktree checks out the COMMITTED config, which may point to a different database than the one the project currently uses (the MCP is the source of truth — `/trocar-banco` keeps it updated).

- Read `~/.claude.json` → `projects["<REPO>"].mcpServers` (fall back to top-level `mcpServers`). Find a DB connection string (`postgresql://user:pass@host:port/<db>` in `args`/`env`, or `PG*`/`DATABASE_URL`). Extract the DB name.
- Skip silently if no MCP DB entry.
- Detect the worktree's app config:
  - Spring → `src/main/resources/application-dev.yml` / `application*.properties` (`spring.datasource.url`)
  - EJB/JSF → `src/main/webapp/WEB-INF/glassfish-resources.xml`
  - .NET → `appsettings*.json`
  - Python → `settings.py`
- If DB differs, edit ONLY the DB name in the connection URL (preserve user, password, host, port, and everything else) and report `🗄 banco ajustado: <before> → <after>`. If already matching, say nothing.

### Step 8 — Rename the session

Display name format: `<type>: <name with separators as spaces>` (e.g. `fix/extrair-informacoes-lacres` → `fix: extrair informacoes lacres`). Skip silently if `~/.config/claude-workspaces/` doesn't exist.

The script is cwd-agnostic — it finds the active session by scanning for the freshest JSONL across all projects (mtime < 120s = this turn), so it works regardless of where the session transcript lives relative to `REPO`:

```bash
python3 - "<type>: <name with spaces>" <<'EOF'
import json, re, sys, time
from pathlib import Path

new_name = sys.argv[1]
cfg = Path.home() / ".config/claude-workspaces"
if not cfg.is_dir():
    sys.exit(0)
projects = Path.home() / ".claude/projects"
uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$", re.I)
cands = [p for p in projects.glob("*/*.jsonl") if uuid_re.match(p.name)]
if not cands:
    sys.exit(0)
cur = max(cands, key=lambda p: p.stat().st_mtime)
if time.time() - cur.stat().st_mtime > 120:
    print("transcript antigo; rename pulado", file=sys.stderr)
    sys.exit(0)
sid = cur.stem
cwd = "/" + cur.parent.name.lstrip("-").replace("-", "/")
marks_path = cfg / "session_marks.json"
try:
    marks = json.loads(marks_path.read_text(encoding="utf-8"))
    assert isinstance(marks, dict)
except Exception:
    marks = {}
entry = marks.get(sid) or {}
entry["custom_name"] = new_name
entry.setdefault("cwd", cwd)
marks[sid] = entry
marks_path.write_text(json.dumps(marks, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"sessao {sid} renomeada para: {new_name}")
EOF
```

> The claude-workspaces app also auto-adopts the worktree and auto-names the session from the branch — this rename is a belt-and-suspenders fallback that produces the same result.

### Step 9 — Summary + EnterPlanMode

**Summary (in Portuguese):** branch name, base (`origin/<BASE>` + short SHA), worktree path(s), files copied, session name (or that rename was skipped).

For multi-repo: note that both repos live under the shared parent `<WS_ROOT>/.worktrees/<type>_<name>/` and can be opened together via **"🌿 Abrir console no grupo"** in the claude-workspaces context menu — cwd = parent folder, `@map-api/...` / `@map-web/...` autocomplete works natively without `--add-dir`.

When claude-workspaces is running: it detects the `git worktree add` from this session's JSONL and makes THIS session adopt the worktree — 🌿 chip + branch appear, runners switch cwd to the worktree, Git panel inspects the worktree's branch. The CLI process keeps the main repo as physical cwd, but for runners/git/chip this session IS the worktree.

**CRITICAL — editing files after worktree creation:** All Read/Edit/Write calls must use absolute **worktree** paths — single-repo: `<REPO>.claude/<WS>_<type>_<name>/...`; multi-repo: `<WS_ROOT>/.worktrees/<type>_<name>/<repo>/...` — NOT the main repo path. Every code change must land in the worktree; the running server won't see changes in the main repo.

**Call `EnterPlanMode`.** The worktree is ready — the natural next step is planning what to implement in it. Plan mode prevents accidental edits or commands in the wrong path before the user aligns on the approach.

---

## Removal mode

1. **List candidates:** `git worktree list`. Scope to `<REPO>.claude/` (single-repo) or `<WS_ROOT>/.worktrees/` (multi-repo groups) — never the main worktree, never worktrees outside those paths. Group multi-repo members as a logical unit (removing a group removes all its members).

2. **Classify each** by `git -C <wt> status --short`, IGNORING these disposable files (the ones the creation skill copies in Step 6 / may modify in Step 7):
   - `CLAUDE.md`, `.claude/settings.local.json`, `.env`, `.env.local`
   - Any project-known local config the creation skill touched (e.g. `src/main/webapp/WEB-INF/glassfish-resources.xml`, `appsettings*.json`, `application-dev.yml`)

   Classification:
   - **Clean** (only ignorable files, or nothing): removable with simple confirmation.
   - **Dirty** (any other modified/untracked file, OR unpushed commits): removable ONLY after explicit second confirmation — never silently.

   Check unpushed commits: `git -C <wt> log --oneline @{u}..HEAD 2>/dev/null` (fallback: `git -C <wt> log --oneline HEAD --not --remotes`).

3. **Confirm:** one `AskUserQuestion` (multiSelect) over ALL candidates — clean ones plain, dirty ones marked "com pendências" with a summary of the files/commits at risk in the description. If the user selects a dirty worktree, ask a **second explicit confirmation** listing exactly what will be lost before removing.

4. **Remove each selected** (separate Bash calls — never one `&&` chain; a single denied step would force a full retry):
   ```bash
   git -C "<wt>" checkout -- <tracked-file>   # revert each MODIFIED tracked config
   git -C "<wt>" clean -fdx <path>            # remove UNTRACKED ignorable paths (scope to path, NOT whole tree)
   # Confirm status is empty before removing:
   git -C "<wt>" status --short
   git worktree remove "<path>"               # clean (status must be empty)
   git worktree remove --force "<path>"       # dirty, ONLY after the explicit second confirmation
   git branch -d "<branch>"                   # -d only; if not merged, keep the branch and report
   ```

   Multi-repo groups: after all members are removed, clean up empty dirs:
   ```bash
   rmdir "<WS_ROOT>/.worktrees/<type>_<name>"   # fails safely if not empty
   rmdir "<WS_ROOT>/.worktrees"                 # fails safely if not empty
   ```

5. **Summary (in Portuguese):** removed / kept (and why) / branches deleted or kept.

---

## Rules

- Creation mode: never delete or move existing worktrees/branches.
- Removal mode: only remove what the user explicitly selected in step 3.
- `worktree remove --force` only after explicit second confirmation listing what will be lost. `branch -D` is forbidden — unmerged branches are always kept and reported.
- Never `rm`/`rm -rf` — the harness blocks it. Use `git checkout --` for modified tracked files and `git clean -fdx <path>` for untracked ones.
- Quote all paths and branch names (repos may have accents/`&` in branch names).
