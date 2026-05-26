---
name: notificar-discord
description: Envia uma notificação para o canal do Discord configurado no claude-workspaces, lendo o webhook do settings.json do app. Aceita um texto livre como argumento (ex /notificar-discord deploy concluído); sem argumento, gera e envia um resumo automático do que foi modificado na sessão. Use ao pedir para avisar no Discord, mandar notificação pro Discord, me avisa quando terminar, ou /notificar-discord.
---

# notificar-discord

Send a notification to the user's Discord channel via the webhook stored in
the claude-workspaces app config. The Discord message content is always
written in **Portuguese (pt-BR)** (the user reads it); these instructions are
in English to save tokens.

## 1. Read the webhook config

Read `~/.config/claude-workspaces/settings.json`; extract `discord_webhook_url`
and `discord_webhook_enabled`.

- File missing/unreadable or URL empty → tell the user it isn't configured
  (point to **Configurações → Notificações → Discord**). Do NOT send.
- `discord_webhook_enabled` is `false` but a URL exists → ask before sending.
- NEVER print the full webhook URL back; call it "o webhook configurado".

## 2. Build the message

**Flags** (may precede the text): `--curto` produces a condensed summary —
just one intro line + the 📊 metrics, skipping the detailed blocks. Strip
recognized flags before treating the rest as free text.

**Argument given** (`/notificar-discord <texto>`): use the text verbatim as the
body; short title from it (fallback "🔔 Claude Workspaces").

**Task failed / error context:** if the work being reported ended in failure,
send the summary anyway with priority `CRITICAL` (red embed) and a clear
failure title — AND report the failure in the chat first. (Default behavior;
the user can ask to suppress the Discord message on failure.)

**No argument → automatic summary.** Inspect everything changed this session,
then write the body as if explaining to a **non-technical person who is curious
and would ask "where? why? what does it now do?"** — plain pt-BR, no jargon
dumps. Gather facts first:

- `git status --short` and `git diff --stat` (staged + unstaged) for the list
  and size of changes; `git diff` on the relevant files to understand intent.
- If nothing is uncommitted, summarize the last commit(s) of this session
  (`git log` + `git show --stat`).

The body MUST cover, in this order:
1. **O que é** — one line: what this change/feature is, in lay terms.
2. **Onde mexeu** — which files/areas changed (group by area, not raw paths
   when possible: "tela de configurações", "envio de notificações", etc.).
3. **Por que** — the reason/problem each change solves.
4. **Comportamento** — what the app now does differently that a user would
   notice.
5. **Quantitativos** — derive from the diff: nº de arquivos alterados, nº de
   classes/funções novas ou tocadas, nº de testes criados/alterados (grep for
   `def test_` / test files), linhas +/- (`--stat`). Omit a metric only if it
   is genuinely zero AND irrelevant.

Beyond the diff/commit, also **analyze the current session itself** and share
anything relevant the diff alone wouldn't show — surface it only if it adds
value (otherwise omit):
- key decisions/tradeoffs made and the reasoning;
- problems hit and how they were solved (or that remain open);
- things tested/verified live and the result (e.g. "webhook respondeu HTTP 204");
- pending TODOs / next steps / known limitations the user should remember;
- anything the user explicitly asked to remember or that changes how the app
  behaves.
Put this under a short **"🧠 Notas da sessão"** sub-block when present.

**⚠️ Pontos de atenção (required analysis).** Always do a critical pass over
the changes and call out, honestly, anything the user should keep an eye on —
even things you did yourself. This is analysis, not a recap of facts. Look for:
- code paths not exercised / lack of automated tests for the new behavior;
- edge cases, error handling, or inputs that might break it;
- security/secret-handling concerns (tokens, URLs, credentials, perms);
- performance or blocking risks (sync I/O on the UI thread, large loops);
- assumptions that may not hold, breaking changes, or migrations needed;
- tech debt introduced and concrete follow-ups worth doing next.
Put these under a **"⚠️ Pontos de atenção"** sub-block. Rank by severity
(most important first). If after a genuine review there is truly nothing worth
flagging, write a single line saying so — never pad it with fluff.

**🚀 Próximos passos (suggestions).** Based ONLY on what was written/created/
modified this session, suggest concrete next steps that naturally build on the
work — features to finish, improvements, tests to add, things to wire up or
version. Keep each to a short actionable line. This is forward-looking
*opportunity*, distinct from **Pontos de atenção** (which is *risk*). Do not
invent scope unrelated to the changes; if nothing meaningful follows from them,
omit the block. Put it under a **"🚀 Próximos passos"** sub-block.

Keep it scannable: a short intro line + bullet points. Pick priority
`HIGH`/`CRITICAL` if the summary reports an error/failure OR a high-severity
point of attention (orange/red embed), else `NORMAL`.

## 3. Identify the project

Always tag the notification with the current project so the user knows which
one it came from. Resolve the name with:

```bash
basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```

Use this value as the embed `workspace` (footer) AND prefix the title with it,
e.g. `[claude-workspaces] ✓ Tarefa concluída`. Append the branch when on a
non-default branch (`git branch --show-current`) → footer like
`claude-workspaces · feat/x`.

## 4. Session metrics

A short **"📊 Sessão"** block (tokens in/out, cache, turns, models, duration)
is appended automatically by the helper below — it reads the current session's
transcript via `resolve_transcript()` and is skipped silently when none is
found. Cost in USD isn't stored in the transcript — don't invent it.

## 5. Send via the app's own helper

All the heavy lifting (transcript resolution, metrics, body splitting, safe
part titles) lives in the tested module
`claude_workspaces.notifications.discord_summary`. Fill `TITULO` and `CORPO`
(and the priority) and run:

```bash
/home/italo/Projetos/claude-workspaces/.venv/bin/python - <<'PY'
import json, pathlib, subprocess
from claude_workspaces.notifications.discord import build_embed_payload, send_webhook
from claude_workspaces.notifications import NotificationPriority
from claude_workspaces.notifications.discord_summary import (
    compute_metrics, format_metrics, make_title, resolve_transcript, split_body,
)

def sh(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception: return ""

cwd = pathlib.Path.cwd()
project = (sh(["git", "rev-parse", "--show-toplevel"]) or str(cwd)).split("/")[-1] or "?"
branch = sh(["git", "branch", "--show-current"])
footer = f"{project} · {branch}" if branch else project

settings = json.loads(
    (pathlib.Path.home() / ".config/claude-workspaces/settings.json").read_text("utf-8")
)
url = settings.get("discord_webhook_url", "").strip()
if not url:
    print("SEM URL — webhook não configurado"); raise SystemExit

title = f"[{project}] TITULO"
metrics = format_metrics(compute_metrics(resolve_transcript(cwd)))
body = """CORPO""" + metrics   # só no resumo automático
priority = NotificationPriority.NORMAL   # use CRITICAL p/ falha (embed vermelho)

chunks = split_body(body)
n, all_ok = len(chunks), True
for i, chunk in enumerate(chunks, 1):
    payload = build_embed_payload(
        title=make_title(title, i, n), body=chunk,
        priority=priority, workspace=footer,
    )
    ok, msg = send_webhook(url, payload)
    all_ok = all_ok and ok
    print(("OK" if ok else "FALHOU"), f"{i}/{n}", msg)
print("TODAS OK" if all_ok else "ALGUMA FALHOU")
PY
```

If `claude_workspaces` is not importable, fall back to a `curl` POST of the same
JSON (`{"embeds":[{"title":...,"description":...,"color":...}]}`). Discord
descriptions cap at 4096 chars — trim if longer.

## 6. Report

- `OK` (HTTP 204): confirm in pt-BR, echoing the title/body sent — never the URL.
- `FALHOU`: show the error and suggest checking the webhook in app settings.
