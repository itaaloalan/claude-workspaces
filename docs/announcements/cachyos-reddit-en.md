# Title

`[Showcase] claude-workspaces — Qt app to manage multiple Claude Code sessions, now on AUR`

# Flair

`Showcase` (or `Tools` if Showcase isn't available)

# Body

Built this because I had 4+ Claude Code sessions open across projects and no clue which one was waiting for me, what each one cost in tokens, or how to grep through old sessions.

`claude-workspaces` is a PySide6/Qt desktop app that gives every project its own workspace (name, folders, settings, CLAUDE.md), embeds an xterm.js terminal, shows a live tree of running sessions with state (Working / Waiting / Done), and adds a bell badge so you know when any agent is waiting on you. Also has git worktree integration so you can spin up multiple parallel agents in the same repo without branch collisions, an IntelliJ-style staging panel, per-workspace token/cost telemetry pulled from Claude's JSONL logs, and full-text search across all past sessions.

Install on CachyOS / Arch:

```
paru -S claude-workspaces
```

That's the entire install. Needs the `claude` CLI on `$PATH` for sessions to actually launch.

v0.1.0, MIT, daily-driver tested on CachyOS + KDE Wayland. 130 tests, CI green. Built specifically because Claude Code is great in isolation but falls apart when you're running several projects through it at once.

Repo: https://github.com/itaaloalan/claude-workspaces
AUR: https://aur.archlinux.org/packages/claude-workspaces

Happy to take bug reports — GNOME especially is undertested, file issues if it acts up.
