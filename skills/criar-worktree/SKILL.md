---
name: criar-worktree
description: "✍️ Criado por mim: Cria uma branch nova + worktree com base na develop (ou na branch principal do repo), em qualquer projeto git. A branch segue o padrao de tipos (feat/, fix/, chore/, refactor/...) e o worktree fica em <repo>.claude/<workspace>_<tipo>_<nome> (workspace resolvido do claude-workspaces), com copia dos arquivos locais nao versionados que o Claude precisa (CLAUDE.md, configs locais). Tambem remove worktrees limpos (/criar-worktree remover). Use ao pedir /criar-worktree, criar um worktree, criar uma branch nova com worktree, ou remover/limpar worktrees."
---

# criar-worktree

Creates a new branch + worktree based on `develop`, in any git project. Also removes clean worktrees on request. Talk to the user in Portuguese.

If the user asked to remove/clean (`/criar-worktree remover`, "remova o worktree", "limpa os worktrees"), go to **Removal mode** below. Otherwise, follow **Flow**.

## Flow

1. **Repo root:** `git rev-parse --show-toplevel` → `REPO`. If not a git repo, stop and tell the user.

2. **Base branch:** prefer `develop`; if it doesn't exist (`git show-ref --verify refs/heads/develop`), fall back to `main`, then `master`. Call it `BASE`. Run `git fetch origin "$BASE"` so the worktree starts from the latest remote state.

3. **Branch name:** derive from what the user asked. Format: `<type>/<name>` where `<type>` follows the conventional prefixes (`feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `perf`). Pick the type from the task description; if ambiguous, ask with `AskUserQuestion`. `<name>` is a short kebab/snake slug, no accents, no spaces. If the user gave no task description at all, ask for type + name.

4. **Workspace name:** read `~/.config/claude-workspaces/workspaces.json` and find the workspace whose `folders` contains `REPO` (path match). Call it `WS`. If no workspace matches (or the file doesn't exist), fall back to the repo directory basename.

5. **Worktree path:** `<REPO>.claude/<WS>_<type>_<name>` (sibling directory pattern, e.g. `/path/ogpms.claude/ogpms_feat_api_xml`). If the path already exists or the branch already exists, stop and report — never overwrite, never `--force`.

6. **Create:**
   ```bash
   git worktree add "<REPO>.claude/<WS>_<type>_<name>" -b "<type>/<name>" "origin/<BASE>"
   ```
   If `origin/<BASE>` doesn't exist (no remote), use local `<BASE>` instead.

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

8. **Rename the current Claude session** so the claude-workspaces sidebar shows the task name. Display name format: `<type>: <name with separators turned into spaces>` (e.g. branch `fix/extrair-informacoes-lacres` → `fix: extrair informacoes lacres`). Skip silently if `~/.config/claude-workspaces/` doesn't exist. Mechanism: write `custom_name` into `~/.config/claude-workspaces/session_marks.json` keyed by the current session id — the app polls this file and updates the sidebar live.
   ```bash
   python3 - "<REPO>" "<type>: <name with spaces>" <<'EOF'
   import json, re, sys, time
   from pathlib import Path

   repo, new_name = sys.argv[1], sys.argv[2]
   cfg = Path.home() / ".config/claude-workspaces"
   if not cfg.is_dir():
       sys.exit(0)  # app não instalado — nada a fazer

   # Diretório de transcripts do projeto (cwd onde a sessão Claude roda)
   enc = re.sub(r"[^A-Za-z0-9]", "-", repo)
   proj = Path.home() / ".claude/projects" / enc
   uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$")
   cands = [p for p in proj.glob("*.jsonl") if uuid_re.match(p.name)]
   if not cands:
       sys.exit(0)
   cur = max(cands, key=lambda p: p.stat().st_mtime)
   # Sessão atual está sendo escrita AGORA (este comando acabou de rodar);
   # mtime velho = provavelmente outra sessão — não renomeia às cegas.
   if time.time() - cur.stat().st_mtime > 120:
       print("transcript mais recente é antigo; rename pulado", file=sys.stderr)
       sys.exit(0)
   sid = cur.stem

   marks_path = cfg / "session_marks.json"
   try:
       marks = json.loads(marks_path.read_text(encoding="utf-8"))
       assert isinstance(marks, dict)
   except Exception:
       marks = {}
   entry = marks.get(sid) or {}
   entry["custom_name"] = new_name
   entry["cwd"] = repo
   marks[sid] = entry
   marks_path.write_text(json.dumps(marks, indent=2, ensure_ascii=False), encoding="utf-8")
   print(f"sessao {sid} renomeada para: {new_name}")
   EOF
   ```

9. **Summary:** report branch name, base (`origin/<BASE>` + short SHA), worktree path, files copied, and the new session name (or that the rename was skipped). Suggest opening a Claude session there if the user intends to work on it now.

## Removal mode

1. **List:** `git worktree list`. Candidates are only the worktrees under `<REPO>.claude/` — never the main worktree, never worktrees elsewhere.

2. **Classify each candidate** by `git -C <wt> status --short`, IGNORING the files this skill copies in step 7 of the creation flow (`CLAUDE.md`, `.claude/settings.local.json`, `.env*`, local configs like `glassfish-resources.xml`) — they make every skill-created worktree look dirty but are disposable:
   - **Clean** (only ignorable files, or nothing): removable with simple confirmation.
   - **Dirty** (any other modified/untracked file): removable ONLY with explicit extra confirmation (see step 3) — never silently.
   Also check for commits not pushed/merged: `git -C <wt> log --oneline @{u}..HEAD 2>/dev/null` (or vs `BASE` if no upstream; fallback `git -C <wt> log --oneline HEAD --not --remotes`). Unpushed commits → treat as dirty.

3. **Confirm:** show the list via `AskUserQuestion` (multiSelect over ALL candidates): clean ones plain, dirty ones clearly marked "com pendências" with the file/commit summary in the description. If the user selects a dirty one, ask a SECOND explicit confirmation for that worktree listing exactly what will be lost (modified files + unpushed commits) before removing.

4. **Remove each selected one**: first revert the ignorable files (`rm` the copied untracked ones, `git -C <wt> checkout -- <file>` for the modified configs), then:
   ```bash
   git worktree remove "<path>"            # clean
   git worktree remove --force "<path>"    # dirty, ONLY after the second explicit confirmation
   git branch -d "<branch>"   # -d only; if it fails (not merged), keep the branch and report
   ```

5. **Summary:** removed / kept (and why) / branches deleted or kept.

## Rules

- In creation mode, never delete or move existing worktrees/branches. In removal mode, only remove what the user explicitly selected in step 3.
- Never `--force`, with ONE exception: `worktree remove --force` on a dirty worktree the user explicitly confirmed after seeing the exact files/commits to be lost (step 3's second confirmation). `branch -D` remains forbidden — unmerged branches are always kept and reported.
- Do NOT touch the current worktree's checkout — everything happens in the new directory.
- Quote all paths and branch names (some repos have accents/`&` in branch names).
- Created by Italo Alan.
