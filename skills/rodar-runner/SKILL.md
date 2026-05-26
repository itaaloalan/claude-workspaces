---
name: rodar-runner
description: Executa os runners do claude-workspaces para o projeto atual, igual ao botao "play" do app (bash -lc + cwd + env do runner). Aceita o nome do runner como argumento (ex /rodar-runner web) ou, sem argumento, lista os runners do workspace atual e pergunta qual(is) rodar. Use ao pedir para rodar/subir/iniciar um runner, o servidor, a api, o web, etc, ou /rodar-runner.
---

# rodar-runner

Starts the claude-workspaces runners for the current project, replicating the **play** button: each runner runs `bash -lc "<start_cmd>"`, in the runner's `cwd`, with the runner's `env` exported on top of the environment. Source: `~/.config/claude-workspaces/workspaces.json` (each workspace has `folders` and `runners` with `name/start_cmd/cwd/env/enabled`). Talk to the user in Portuguese.

## Steps

1. **Resolve runners** for the current project, from the session's folder:
   ```bash
   python3 ~/.claude/skills/rodar-runner/resolve_runners.py [NOME ...]
   ```
   - Pass the skill's arguments as `NOME`.
   - JSON output: `{workspace, matched_folder, runners:[...]}`. If it returns `{"error":...}` (exit 2), the folder doesn't match any workspace: show the `workspaces` list and ask which folder to run in (or rerun with `--cwd <folder>`).

2. **Choose:** with arg and 1 match -> use it; with arg and several -> `AskUserQuestion`; no arg -> list them (name + start of `start_cmd`, marking `enabled:false` as disabled) and ask via `AskUserQuestion` (allow multiple). `enabled:false` runners only run if explicitly requested.

3. **Run** each chosen one in detached background (they're long-lived servers), with Bash `run_in_background: true`:
   ```bash
   setsid bash -lc 'cd <cwd> && <start_cmd>' > /tmp/runner-<nome>.log 2>&1 < /dev/null &
   ```
   - Substitute `<cwd>`/`<start_cmd>`. If there's an `env`, prefix `export K=V; ...` inside the `bash -lc`.
   - Watch out for quotes (the `start_cmd` may contain quotes) — build the command carefully / via heredoc.

4. **Report** per runner: name, PID/log (`/tmp/runner-<nome>.log`), how to follow (`tail -f`) and stop (`kill <pid>`). Don't sit in the foreground waiting — the server doesn't end.

## Notes

- This skill only fires the `start_cmd` like play; it does NOT manage stop/restart/URL detection (that's the app).
- A busy port is normally already handled by the `start_cmd` itself (e.g. `fuser -k`) — don't invent stop logic.
