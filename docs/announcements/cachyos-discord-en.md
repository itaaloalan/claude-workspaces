# Discord — #showcase

Posting target: official CachyOS Discord, `#showcase` channel.

Keep it ~5 lines. Drop a screenshot (or short GIF) above the text if you have one.

---

Hey folks — built `claude-workspaces`, a Qt/PySide6 app that manages multiple Claude Code sessions per project: embedded terminal, live "who's waiting on you" tree, git worktrees for parallel agents, per-workspace token costs, and full-text search across old sessions.

It's on the AUR now:
```
paru -S claude-workspaces
```

v0.1.0, MIT, daily-tested on CachyOS + KDE Wayland. 130 tests, CI green. Honest expectations: GNOME is undertested, MCP only does postgres for now.

Repo + issues: <https://github.com/itaaloalan/claude-workspaces>

Would love feedback / bug reports — especially from folks running several Claude sessions in parallel.
