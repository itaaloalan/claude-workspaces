---
name: trocar-banco
description: Troca o banco configurado no arquivo de config do projeto atual (ou de um dos workspaces) para um Postgres local. Detecta o stack (Spring->application-*.yml/properties, EJB/JSF->glassfish-resources.xml, .NET->appsettings.json, Python->settings.py), lista bancos locais por prefixo do projeto e atualiza o arquivo preservando o resto. Opcionalmente atualiza o MCP em ~/.claude.json. Use ao pedir /trocar-banco ou para trocar/mudar o banco de qualquer projeto.
---

# trocar-banco

Switches the DB pointed to in the project's config file to a local Postgres, regardless of stack. Detects the type, edits the right file, and (optionally) syncs the matching MCP in `~/.claude.json`. Talk to the user in Portuguese.

## Steps

1. **Detect candidates** in each working dir (cwd + additional):

   | Type | File |
   |------|---------|
   | `glassfish` | `src/main/webapp/WEB-INF/glassfish-resources.xml` |
   | `spring` | `src/main/resources/application-dev.yml` (or `application.yml`/`.properties`) with a `datasource` block |
   | `dotnet` | `appsettings.json` / `appsettings.Development.json` at the root |
   | `python` | `settings.py` at the root, or `manage.py` + `*/settings.py` |

   Pure frontend (none of these files) is ignored.

2. **Choose project:** 1 candidate -> use it and inform; several -> `AskUserQuestion` (label=dir, desc=path+type); none -> stop and warn. From here, paths are relative to `$PROJ`.

3. **MCP + credentials:** infer the MCP from the project name in `~/.claude.json`->`mcpServers`. No clear match, ask (or skip). Extract user/pass/host/port/db from the connection string:

   ```bash
   python3 -c "
   import json, re, os
   cfg = json.load(open(os.path.expanduser('~/.claude.json')))
   url = cfg['mcpServers']['<NOME_MCP>']['args'][-1]
   u,p,h,pt,db = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', url).groups()
   print(f'user={u}\nhost={h}\nport={pt}\npass={p}\ndb={db}')"
   ```
   If it doesn't parse, ask the user for the credentials.

4. **Show current DB** per type: glassfish->`grep -E "databaseName|URL" $PROJ/.../glassfish-resources.xml | head -2`; spring->`url/username/password` lines of the datasource; dotnet->`ConnectionStrings`; python->`DATABASES['default']`.

5. **List local DBs** filtering by the project's short name (case-insensitive); if empty, list all:
   ```bash
   PGPASSWORD="<senha>" psql -h <host> -U <user> -lqt 2>/dev/null \
     | awk -F'|' '{gsub(/^ +| +$/,"",$1); print $1}' | grep -i "<filtro>" | sort
   ```
   If listing fails, report and STOP — don't guess.

6. **Ask which DB:** up to 4 -> `AskUserQuestion` (mark the current one); more -> numbered list.

7. **Update config** touching ONLY the relevant fields, UTF-8, preserving the rest:
   - **glassfish:** regex on each `<property name="X" value="...">` for `serverName`(host), `portNumber`(port), `databaseName`(db), `User`, `Password`, `URL`(`jdbc:postgresql://host:port/db`).
   - **spring yml:** usually `${VAR:default}` — replace the **default** (after the `:`) of the url/user/pass vars (find the names by reading the file). If literal values, edit the `url/username/password` lines preserving indentation. Multiple `application-*.yml` with a datasource -> ask which.
   - **spring properties:** replace `spring.datasource.url/.username/.password` line by line.
   - **dotnet:** parse JSON, update `ConnectionStrings.<name>` (usually `DefaultConnection`), keep indentation.
   - **python:** edit `DATABASES['default']` (`NAME/USER/PASSWORD/HOST/PORT`) via line-by-line regex.

8. **Verify:** quick `grep` confirming (same keys as step 4).

9. **MCP?** `AskUserQuestion`: update the MCP `<name>` in `~/.claude.json` to `<db>`? If yes, set `mcpServers[NOME]['args'][-1]` to `postgresql://user:pass@host:port/db` (json.dump indent=2). Warn: the MCP only takes effect in new sessions.

10. **Summary:** project+type, file updated, host/port/database/user, MCP updated|kept.

## Critical rules

- NEVER switch to a remote PRODUCTION DB (`*.rds.amazonaws.com`, `*.supabase.co`, etc) — if the current config points there, WARN first.
- NEVER use a DB outside the psql listing — on an invalid choice, refuse and ask again.
- ALWAYS preserve the rest of the file; touch only the type's fields. Encoding UTF-8.
- NEVER commit the change. NEVER touch `~/.claude.json` without confirmation (step 9).
- YAML `${VAR:default}`: edit the default — don't remove the placeholder or add a new literal field.
