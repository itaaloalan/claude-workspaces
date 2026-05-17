# [Showcase] claude-workspaces — a workspace manager for Claude Code (AUR available)

Hi everyone,

I've been building a desktop app for the past few weeks that solves a problem I kept hitting while juggling several Claude Code sessions across projects, and I think CachyOS users in particular might get value out of it because it's already on the AUR and runs natively on PySide6/Qt — no Electron.

## The problem

Claude Code is powerful, but when you run it across multiple projects at the same time, the workflow falls apart fast:

- Multiple terminal windows lose context between them
- You don't know which session is waiting for input and which is still working
- Token spend goes unmonitored
- Old sessions are hard to grep through
- Worktrees / branches collide if you run several agents on the same repo

## What `claude-workspaces` gives you

- **Workspaces**: each project gets a name, a list of folders, and its own settings. Launching Claude from a workspace passes those folders as isolated context.
- **Embedded terminal** (xterm.js + pty): multiple Claude tabs per workspace, no external windows.
- **Global inbox**: a bell badge in the topbar notifies you when any console finishes and is waiting (✓ "Waiting").
- **Sidebar with live activity tree**: every running console shows up under its workspace with real-time state (Working · spinner / Waiting ❚❚ / Done ✓) and the session title.
- **Optional worktrees**: when launching Claude, choose to isolate it in a git worktree on a new (or existing) branch — handy for running multiple agents on the same repo in parallel.
- **IntelliJ-style Git panel**: file tree with checkboxes to selectively stage and commit inline. Right-click for Add/Unstage/Rollback/Delete.
- **Per-workspace token/cost telemetry** (reads the Claude JSONL logs directly).
- **Skills / Agents / Commands** listed with filters, usage counters (% and last-used), click to copy `/name`.
- **Workspace memory**: inline editor for the primary folder's CLAUDE.md.
- **Search across all past sessions** (Ctrl+Shift+F): free-text grep with snippets.
- **Handoff**: a "→ Task" button passes context from one session to another with a pre-filled briefing.
- **MCP postgres**: create/edit the Claude MCP postgres config per workspace.

## Install on CachyOS / Arch

```bash
paru -S claude-workspaces
# or
yay -S claude-workspaces
```

That's it — the AUR PKGBUILD pulls PySide6 from the repos and the `.desktop` lands in your menu. You'll need the `claude` CLI (Anthropic's Claude Code) on `$PATH` for the actual sessions to launch.

If you want HEAD instead of the tagged release, the manual route is:

```bash
git clone https://github.com/itaaloalan/claude-workspaces.git
cd claude-workspaces
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/claude-workspaces
```

## Honest status

- **v0.1.0**, in daily personal use, 130 tests, CI green.
- Built and tested on CachyOS + KDE Wayland.
- Open issues / pain points: GNOME hasn't been stress-tested, the dock-right plugin API is documented but young, and the MCP integration only covers postgres for now.
- MIT licensed.

## Why I'm posting here first

Two reasons:

1. The AUR package is the lowest-friction way to try it, so CachyOS / Arch folks can give feedback fastest.
2. CachyOS users tend to actually file good issues, which is what I need before pushing this to broader audiences.

If you try it, I'd love bug reports on the [GitHub tracker](https://github.com/itaaloalan/claude-workspaces/issues), or just reply here with what didn't make sense. I'll be around for the next few days.

— Italo

Repo: https://github.com/itaaloalan/claude-workspaces
AUR: https://aur.archlinux.org/packages/claude-workspaces
