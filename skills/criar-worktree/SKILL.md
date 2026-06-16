---
name: criar-worktree
description: "✍️ Criado por mim: Creates a new branch + worktree in any git project, ALWAYS asking which base branch to use (conventional dev/develop/main/master plus the currently checked-out branch, e.g. a release/correction branch). The branch follows the type-prefix convention (feat/, fix/, chore/, refactor/...) and the worktree lives at <repo>.claude/<workspace>_<type>_<name> (workspace resolved from claude-workspaces), with a copy of the local untracked files Claude needs (CLAUDE.md, local configs). When several worktrees are created together in a multi-repo workspace (e.g. MAP's map-api + map-web), it cross-links them via permissions.additionalDirectories so all load in one session without manual /add-dir. Also removes clean worktrees (/criar-worktree remover). When several worktrees are created together in a multi-repo workspace (e.g. MAP's map-api + map-web), it creates them under a shared parent folder (<WS_ROOT>/.worktrees/<type>_<name>/<repo>) so opening the console with cwd=parent gives first-class @ autocomplete for all repos without add-dir. Use when the user asks /criar-worktree, criar um worktree, criar uma branch nova com worktree, or to remove/clean worktrees."
---

# criar-worktree

Creates a new branch + worktree in any git project. It **always asks** which base branch to use — the conventional `dev`/`develop`/`main`/`master`, plus the currently checked-out branch (often a release/correction branch like `v2.3.x-correções_branch`) — never assuming a default. Also removes clean worktrees on request.

**Language:** talk to the user in Portuguese (pt-BR) — questions, warnings, and summaries. Branch names follow the Portuguese slug conventions described below.

**Mode selection:** if the user asked to remove/clean (`/criar-worktree remover`, "remova o worktree", "limpa os worktrees"), go to **Removal mode** below. Otherwise, follow **Creation flow**.

## Creation flow

1. **Repo root:** `git rev-parse --show-toplevel` → `REPO`. If not a git repo, stop and tell the user.

2. **Base branch — ALWAYS ASK:** NEVER assume the base branch. Always ask the user with `AskUserQuestion` which branch to base the worktree on, **even when only one conventional branch exists**. Do not skip this question — the user frequently wants a non-default base (a release/correction branch, a teammate's branch, etc.), and silently defaulting to `dev`/`master` is wrong.
   - Detect the conventional base branches present **locally OR on the remote** — check `dev`, `develop`, `main`, `master`, in this priority order:
     ```bash
     for b in dev develop main master; do
       if git show-ref --verify -q "refs/heads/$b" || git show-ref --verify -q "refs/remotes/origin/$b"; then echo "$b"; fi
     done
     ```
   - Also capture the **currently checked-out branch** (`git rev-parse --abbrev-ref HEAD`). Release/correction/feature branches (e.g. `v2.3.x-correções_branch`) are common, valid bases and will NOT appear in the conventional list — the user is often working off the current branch and wants the worktree based on it.
   - Build the `AskUserQuestion` options:
     - If the current branch is NOT one of the conventional ones, make it the **first** option and mark it `(Recommended)` — the user is probably working off it.
     - Otherwise make the highest-priority conventional branch (`dev` > `develop` > `main` > `master`) the first option and mark it `(Recommended)`.
     - Include the other detected conventional branches as the remaining options. The user can always type "Other" to give any branch name (handle accents/`&`).
   - When useful, show whether each candidate exists on the remote and is in sync — this helps the user choose.
   - If NONE of the conventional branches exist AND there is no usable current branch, stop and warn the user.

   Once the user picks `BASE`, fetch it — but only if an `origin` remote exists (consistent with the no-remote fallback in step 6): `git remote get-url origin >/dev/null 2>&1 && git fetch origin "$BASE"`. This way the worktree starts from the latest remote state. Prefer `origin/<BASE>` as the start point in step 6; only fall back to local `<BASE>` if `origin/<BASE>` doesn't exist.

3. **Branch name:** derive from what the user asked. Format: `<type>/<name>` where `<type>` follows the conventional prefixes (`feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`). Pick the type from the task description; if ambiguous, ask with `AskUserQuestion`. `<name>` is a short kebab/snake slug, no accents, no spaces. If the user gave no task description at all, ask for type + name.

4. **Workspace name:** read `~/.config/claude-workspaces/workspaces.json` and find the workspace whose `folders` contains `REPO` (path match). Call it `WS`. If no workspace matches (or the file doesn't exist), fall back to the repo directory basename.

   **Multi-repo selection:** if the workspace has more than one folder (repo), ask with `AskUserQuestion` (multiSelect) which repos to create the worktree in. Include all workspace folders as options; mark the project-relevant default pre-selected (use project memory if available — e.g. for MAP: `map-api + map-web`). The answer determines the mode:
   - 1 repo selected → **single-repo** path convention (step 5 below).
   - 2+ repos selected → **multi-repo (pasta-pai)** convention (step 5 below).

   If the workspace has only one folder, skip this question (single-repo mode).

5. **Worktree path:** depends on the number of repos selected in step 4:

   - **Single-repo:** `<REPO>.claude/<WS>_<type>_<name>` (sibling directory pattern, e.g. `/path/ogpms.claude/ogpms_feat_api_xml`).
   - **Multi-repo (2+ repos together, e.g. MAP):** for each selected repo, the path is `<WS_ROOT>/.worktrees/<type>_<name>/<repo-basename>`, where `<WS_ROOT>` is the common parent of all selected repos (`os.path.commonpath([repo_a, repo_b, ...])`). Example: `/home/.../map/map-api` + `/home/.../map/map-web` → `<WS_ROOT>` = `/home/.../map` → worktrees at `/home/.../map/.worktrees/feat_xyz/map-api` and `.../map-web`.

   In both cases: if the path already exists or the branch already exists, stop and report — never overwrite, never `--force`. Run existence checks as their own commands; do NOT fold them into the create command (see the warning in step 6).

6. **Create:**

   - **Single-repo:**
     ```bash
     git worktree add "<REPO>.claude/<WS>_<type>_<name>" -b "<type>/<name>" "origin/<BASE>"
     ```
   - **Multi-repo:** first `mkdir -p "<WS_ROOT>/.worktrees/<type>_<name>"`, then one command per repo (each as its own Bash call):
     ```bash
     git -C "<REPO_A>" worktree add "<WS_ROOT>/.worktrees/<type>_<name>/<REPO_A_BASENAME>" -b "<type>/<name>" "origin/<BASE>"
     git -C "<REPO_B>" worktree add "<WS_ROOT>/.worktrees/<type>_<name>/<REPO_B_BASENAME>" -b "<type>/<name>" "origin/<BASE>"
     ```

   If `origin/<BASE>` doesn't exist (no remote), use local `<BASE>` instead.

   **Run each as its own Bash call with the path and branch written out LITERALLY — never via shell variables (`$WT`/`$BR`), never wrapped in an `if/elif/else`.** The claude-workspaces app auto-adopts the worktree by statically parsing this exact command from the session transcript (`scan_worktree_adds`); it does NOT expand shell variables, so a command like `git worktree add "$WT" -b "$BR"` is parsed as the literal path `$WT`, fails validation, and is silently discarded — the session never gets the 🌿 worktree badge. Keep any existence guard (step 5) in separate prior commands so the create command stays a clean, literal `git worktree add "<path>" -b "<branch>" "<base>"`. For multi-repo, the `-C "<repo>"` flag routes to the correct repo; `scan_worktree_adds` still picks up the path (it scans for the `worktree add` token pair regardless of preceding flags).

7. **Copy Claude-local files** (untracked/local-only files the new worktree won't have). For each, copy only if it exists in `REPO` and is NOT tracked by git (`git ls-files --error-unmatch <file>` fails) or differs locally:
   - `CLAUDE.md` (if untracked)
   - `.claude/settings.local.json`
   - `.env`, `.env.local` (if untracked)
   - Project-known local configs with uncommitted changes (e.g. OGPMS `src/main/webapp/WEB-INF/glassfish-resources.xml`): copy the working-tree version over the worktree's checked-out one.

   List what was copied.

7.5. **Sync the database config to the project's MCP.** The worktree checks out the COMMITTED config, which may point to a different database than the one the project currently uses (the MCP is the source of truth — `/trocar-banco` keeps it updated). Steps:
   - Read `~/.claude.json` → `projects["<REPO>"].mcpServers` (fall back to top-level `mcpServers`). Find the database entry: a connection string `postgresql://user:pass@host:port/<db>` in `args`/`env`, or `PG*`/`DATABASE_URL` env vars. Extract the database name (and host/port).
   - If there is no MCP database entry, skip this step silently.
   - Detect the worktree's app config (same table as `/trocar-banco`):
     - Spring → `src/main/resources/application-dev.yml` / `application*.properties` (`spring.datasource.url`)
     - EJB/JSF → `src/main/webapp/WEB-INF/glassfish-resources.xml`
     - .NET → `appsettings*.json`
     - Python → `settings.py`
   - Compare the database in the worktree config with the MCP one. If they differ, edit ONLY the database part of the URL/property in the WORKTREE file (preserve user, password, host, port and everything else) and report `🗄 banco ajustado: <antes> → <depois>`. If they already match, say nothing.

7.6. **Multi-repo grouping (pasta-pai):** when the multi-repo case applied (steps 4-6), the worktrees already live under a shared parent folder (`<WS_ROOT>/.worktrees/<type>_<name>/`), so NO `additionalDirectories` wiring is needed. To open both repos together in a single Claude session, use the **"🌿 Abrir console no grupo"** action in the claude-workspaces app (context-menu on the workspace) — it opens the console with `cwd` = the parent folder and zero `--add-dir`, making `@map-api/...` and `@map-web/...` autocomplete work natively. **Skip entirely when only a single worktree was created.**

8. **Rename the current Claude session** so the claude-workspaces sidebar shows the task name. Display name format: `<type>: <name with separators turned into spaces>` (e.g. branch `fix/extrair-informacoes-lacres` → `fix: extrair informacoes lacres`). Skip silently if `~/.config/claude-workspaces/` doesn't exist. Mechanism: write `custom_name` into `~/.config/claude-workspaces/session_marks.json` keyed by the current session id — the app polls this file and updates the sidebar live. (Note: when the app is open it ALSO auto-adopts the worktree into THIS session and auto-names it after the branch — see step 9 — so this rename is a belt-and-suspenders fallback that produces the same name; harmless if it runs too.)

   **Do NOT assume the session transcript lives under the dir encoded from `<REPO>`** — the Claude session cwd is often a SUBDIR of the repo (e.g. SIPE's registered workspace folder is `<REPO>/src`, so the transcript dir is `…-sipe-sipe-src`, not `…-sipe-sipe`). Encoding from `<REPO>` then finds nothing and the rename silently no-ops. The script below is cwd-agnostic: it scans ALL `~/.claude/projects/*` dirs and picks the single freshest `*.jsonl` (the one being written THIS turn, mtime < 120s) — that is the active session regardless of cwd. No path argument needed.
   ```bash
   python3 - "<type>: <name with spaces>" <<'EOF'
   import json, re, sys, time
   from pathlib import Path

   new_name = sys.argv[1]
   cfg = Path.home() / ".config/claude-workspaces"
   if not cfg.is_dir():
       sys.exit(0)  # app não instalado — nada a fazer

   # A sessão ATIVA é o transcript com a escrita mais recente, em QUALQUER projeto.
   # (o cwd da sessão pode ser um subdir do repo — não dá pra derivar o dir de <REPO>)
   projects = Path.home() / ".claude/projects"
   uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$")
   cands = [p for p in projects.glob("*/*.jsonl") if uuid_re.match(p.name)]
   if not cands:
       sys.exit(0)
   cur = max(cands, key=lambda p: p.stat().st_mtime)
   # Esse transcript está sendo escrito AGORA (este comando acabou de rodar);
   # mtime velho = provavelmente outra sessão — não renomeia às cegas.
   if time.time() - cur.stat().st_mtime > 120:
       print("transcript mais recente é antigo; rename pulado", file=sys.stderr)
       sys.exit(0)
   sid = cur.stem
   # cwd real da sessão = dir do transcript decodificado (informativo p/ o app)
   cwd = "/" + cur.parent.name.lstrip("-").replace("-", "/")

   marks_path = cfg / "session_marks.json"
   try:
       marks = json.loads(marks_path.read_text(encoding="utf-8"))
       assert isinstance(marks, dict)
   except Exception:
       marks = {}
   entry = marks.get(sid) or {}
   entry["custom_name"] = new_name
   entry.setdefault("cwd", cwd)  # só preenche se ainda não houver (decode é aproximado)
   marks[sid] = entry
   marks_path.write_text(json.dumps(marks, indent=2, ensure_ascii=False), encoding="utf-8")
   print(f"sessao {sid} renomeada para: {new_name}")
   EOF
   ```

9. **Summary (in Portuguese):** report branch name, base (`origin/<BASE>` + short SHA), worktree path(s) (for multi-repo: the shared parent folder `<WS_ROOT>/.worktrees/<type>_<name>/`), files copied, and the new session name (or that the rename was skipped). For multi-repo, also instruct: open both repos together via "🌿 Abrir console no grupo" in the claude-workspaces context menu. Do NOT suggest "opening a Claude session in the worktree" for single-repo — it's redundant. When the claude-workspaces app is running, it detects the `git worktree add` from this session's JSONL (`scan_worktree_adds`) and makes THIS session adopt the worktree automatically: the 🌿 chip + branch label appear, this console's runners switch their default cwd to the worktree (so play/deploy runs there), the Git panel inspects the worktree's branch, and the session is auto-named after the branch. The Claude CLI process keeps the main repo as its physical cwd, but for runners/git/name/chip this session already IS the worktree's session. At most, note that this session has already assumed the worktree.

   **CRITICAL — editing files after worktree creation:** Once the 🌿 chip is active, the server/app runs from the **worktree path**, not from the main repo. All subsequent file edits (Read/Edit/Write) MUST use the worktree path — single-repo: `<REPO>.claude/<WS>_<type>_<name>/...`; multi-repo: `<WS_ROOT>/.worktrees/<type>_<name>/<repo>/...` — NOT the main repo path. The Claude process's physical cwd does not change, but every code change must land in the worktree — otherwise the running server never sees it. Always derive the full worktree-relative path before any edit: replace the main repo root with the worktree root.

10. **Return to plan mode:** After delivering the summary, call `EnterPlanMode`. The worktree is ready — the next action is naturally planning what to implement in it, and plan mode prevents accidental file edits or command runs in the wrong path before the user aligns on the approach.

## Removal mode

1. **List:** `git worktree list`. Candidates are the worktrees under `<REPO>.claude/` (single-repo) or under `<WS_ROOT>/.worktrees/` (multi-repo groups) — never the main worktree, never worktrees elsewhere. For multi-repo groups, list all member worktrees together as a logical unit (removing a group removes all its members).

2. **Classify each candidate** by `git -C <wt> status --short`, IGNORING the files this skill copies in step 7 of the creation flow (`CLAUDE.md`, `.claude/settings.local.json`, `.env*`, local configs like `glassfish-resources.xml`) — they make every skill-created worktree look dirty but are disposable:
   - **Clean** (only ignorable files, or nothing): removable with simple confirmation.
   - **Dirty** (any other modified/untracked file): removable ONLY with explicit extra confirmation (see step 3) — never silently.

   Also check for commits not pushed/merged: `git -C <wt> log --oneline @{u}..HEAD 2>/dev/null` (or vs `BASE` if no upstream; fallback `git -C <wt> log --oneline HEAD --not --remotes`). Unpushed commits → treat as dirty.

3. **Confirm:** show the list via `AskUserQuestion` (multiSelect over ALL candidates): clean ones plain, dirty ones clearly marked "com pendências" with the file/commit summary in the description. If the user selects a dirty one, ask a SECOND explicit confirmation for that worktree listing exactly what will be lost (modified files + unpushed commits) before removing.

4. **Remove each selected one:** first revert the ignorable files, then remove the worktree, then drop the branch. **Always use git to clean up — never `rm`/`rm -rf`.** The harness permission layer blocks `rm -rf` (it gets denied, costing a round of trial-and-error), while `git checkout`/`git clean` are allowed and do exactly the same job safely:
   ```bash
   git -C "<wt>" checkout -- <tracked-file>   # revert each MODIFIED tracked config (e.g. appsettings.json, glassfish-resources.xml)
   git -C "<wt>" clean -fdx <path>            # remove each UNTRACKED ignorable path (e.g. .dotnet/, .env created locally) — scope to the path, do NOT clean the whole tree blindly
   git worktree remove "<path>"               # clean (now that ignorable files are gone)
   git worktree remove --force "<path>"       # dirty, ONLY after the second explicit confirmation
   git branch -d "<branch>"                    # -d only; if it fails (not merged), keep the branch and report
   ```
   Run these as separate Bash calls (revert → clean → remove → branch), not one big `&&` chain — a single denied step in a chain forces you to redo the whole thing. After the revert+clean, `git -C "<wt>" status --short` must be empty before the plain `git worktree remove`.

   For multi-repo groups: after all member worktrees are removed, remove the group parent folder if empty (`rmdir "<WS_ROOT>/.worktrees/<type>_<name>"`) and `.worktrees/` itself if it becomes empty too (`rmdir "<WS_ROOT>/.worktrees"`). `rmdir` fails safely if not empty — no `rm -rf`.

5. **Summary (in Portuguese):** removed / kept (and why) / branches deleted or kept.

## Rules

- In creation mode, never delete or move existing worktrees/branches. In removal mode, only remove what the user explicitly selected in step 3.
- Never `--force`, with ONE exception: `worktree remove --force` on a dirty worktree the user explicitly confirmed after seeing the exact files/commits to be lost (step 3's second confirmation). `branch -D` remains forbidden — unmerged branches are always kept and reported.
- Do NOT touch the current worktree's checkout — everything happens in the new directory.
- **Never use `rm`/`rm -rf` to clean a worktree** — the harness blocks it. Use `git -C <wt> checkout -- <file>` for modified tracked files and `git -C <wt> clean -fdx <path>` for untracked ones (see Removal step 4).
- Quote all paths and branch names (some repos have accents/`&` in branch names).
- Created by Italo Alan.
