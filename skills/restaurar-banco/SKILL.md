---
name: restaurar-banco
description: Restaura um dump PostgreSQL (.backup/.dump custom-format ou .sql) num banco LOCAL. O arquivo de origem está sempre em /home/italo/backup_bancos/ e o destino é sempre o Postgres local (localhost:5432, user postgres). Pergunta apenas duas coisas — qual arquivo e o nome do banco de destino — cria o banco e restaura. Use quando o usuário pedir /restaurar-banco ou pedir para restaurar/subir um backup de banco localmente.
---

# Skill: restaurar-banco

Talk to the user in Portuguese.

Restores a PostgreSQL backup into a **local** database, from the fixed directory `/home/italo/backup_bancos/`.

Fixed local credentials: host `localhost`, port `5432`, user `postgres`, password `qwe123`. ALWAYS use `PGPASSWORD=qwe123` in commands (the shell is fish — do NOT rely on `export`; prefix the variable on the command line itself, e.g. `PGPASSWORD=qwe123 psql ...`).

## Only ask two things

1. **Which file** to restore (inside `/home/italo/backup_bancos/`).
2. **What is the name** of the destination database.

Do NOT ask for host/user/password/port — they are fixed. Do NOT ask if it is local — it is always local.

## Mandatory flow

### 1. Resolve the source file

- If the user already named the file, use it (accept an absolute path or just the name — if just the name, prefix `/home/italo/backup_bancos/`).
- If not, **list the available backups** and ask them to choose:
  ```
  ls -lht /home/italo/backup_bancos/
  ```
  Use `AskUserQuestion` with the most recent files as options (newest first).
- Confirm the file exists and detect the format:
  ```
  file /home/italo/backup_bancos/<arquivo>
  ```
  - "PostgreSQL custom database dump" → restore with `pg_restore`.
  - text/`ASCII`/`.sql` → restore with `psql -f`.

### 2. Resolve the destination database name

- If the user gave the name, use it.
- If not, suggest a name derived from the dump's original dbname (see below) and ask.

To find the dump's original dbname (custom-format):
```
pg_restore -l /home/italo/backup_bancos/<arquivo> | grep -i "dbname"
```

### 3. Check if the database already exists and confirm

```
PGPASSWORD=qwe123 psql -h localhost -U postgres -lqt | cut -d'|' -f1 | grep -wq <banco>
```
- If it **already exists**: warn and **confirm with the user** before dropping (`DROP DATABASE` erases everything). Only proceed with an explicit OK.
- If it does not exist: continue.

### 4. Create the database and restore

Create (drop only after the confirmation in step 3):
```
PGPASSWORD=qwe123 psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS <banco>;" -c "CREATE DATABASE <banco> OWNER postgres;"
```

Restore — **custom-format** (`.backup`/`.dump`):
```
PGPASSWORD=qwe123 pg_restore -h localhost -U postgres -d <banco> --no-owner --role=postgres -j 4 /home/italo/backup_bancos/<arquivo>
```
- `--no-owner --role=postgres` remaps owners from the original dump to the local `postgres` (the source dbname/owner usually differs, e.g. `map_dev_pt` dumps).
- `-j 4` speeds it up (parallel). For very large dumps you may raise the command timeout (up to 600000 ms).

Restore — **plain SQL** (`.sql`):
```
PGPASSWORD=qwe123 psql -h localhost -U postgres -d <banco> -f /home/italo/backup_bancos/<arquivo>
```

### 5. Validate and report

```
PGPASSWORD=qwe123 psql -h localhost -U postgres -d <banco> -c "SELECT count(*) AS tabelas FROM information_schema.tables WHERE table_schema='public';"
```
Report: database created, number of tables, and warn about relevant `pg_restore` errors (some `--no-owner` warnings about nonexistent roles are expected and harmless).

## Notes

- Errors like "role ... does not exist" or "schema ... already exists" during `pg_restore` with `--no-owner` are usually benign; only highlight them if they affect data/tables.
- Do NOT switch any project's config to point to the restored database — that is the `trocar-banco` skill. If the user wants to point the app at the new database, suggest `/trocar-banco`.
