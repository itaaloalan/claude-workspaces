"""Expansão do placeholder {port} nos campos de um runner.

A expansão acontece SÓ na hora de rodar (runner_widget._spawn e fluxo de
browser) — o que se persiste é a `port` numérica; os comandos guardam
`{port}` literal.
"""

from __future__ import annotations

import re


def expand_port(text: str, port: int) -> str:
    """Substitui `{port}` por `port` em `text`. `port <= 0` → intacto.

    Usa str.replace, NUNCA str.format — comandos shell têm `{}` legítimos
    (awk '{print}', ${VAR}, JSON inline) que o format() quebraria.
    """
    if port <= 0:
        return text
    return text.replace("{port}", str(port))


def apply_port_arg(cmd: str, port: int) -> str | None:
    """Aplica a porta automaticamente em dev servers conhecidos quando o
    comando não usa `{port}` — anexa a flag ao FINAL do comando, onde a
    ÚLTIMA ocorrência vence (yargs/cac do ng/vite), sobrepondo porta
    hardcoded em script do package.json.

    Retorna o comando com a flag, ou None quando não reconhece o padrão
    (aí valem as envs PORT/SERVER_PORT e o aviso ⚠ de descompasso).
    """
    if port <= 0 or not cmd.strip():
        return None
    # Último segmento do encadeamento shell — é nele que o append atua.
    last = re.split(r"&&|;", cmd)[-1].strip()
    if not last:
        return None
    if re.match(r"(?:npx\s+)?ng\s+serve\b", last):
        return f"{cmd} --port {port}"
    if re.match(r"(?:npx\s+)?vite\b", last):
        return f"{cmd} --port {port}"
    if re.match(r"(?:npx\s+)?next\s+(?:dev|start)\b", last):
        return f"{cmd} -p {port}"
    if re.match(r"npm\s+(?:start\b|run\s+\S+)", last):
        sep = "" if re.search(r"\s--(?:\s|$)", last) else " --"
        return f"{cmd}{sep} --port {port}"
    if re.match(r"pnpm\s+\S+", last):
        sep = "" if re.search(r"\s--(?:\s|$)", last) else " --"
        return f"{cmd}{sep} --port {port}"
    if re.match(r"yarn\s+\S+", last):
        return f"{cmd} --port {port}"
    return None


# Bootstrap de dependências node pra diretório recém-criado: worktree novo
# não tem node_modules, então binários locais (`ng`, `vite`, …) quebram com
# "comando não encontrado". Só dispara quando há package.json SEM
# node_modules no cwd do runner; respeita o lockfile (pnpm/yarn/npm). Se o
# install falhar, o comando original nem roda (&&) — o erro real aparece.
_NODE_BOOTSTRAP = (
    "if [ -f package.json ] && [ ! -d node_modules ]; then "
    "echo '📦 node_modules ausente — instalando dependências…'; "
    "if [ -f pnpm-lock.yaml ]; then pnpm install; "
    "elif [ -f yarn.lock ]; then yarn install; "
    "else npm install; fi; "
    "fi && "
)


def wrap_with_node_bootstrap(cmd: str) -> str:
    """Prefixa `cmd` com o bootstrap de node_modules (no-op em diretórios
    sem package.json ou já instalados)."""
    if not cmd.strip():
        return cmd
    return _NODE_BOOTSTRAP + cmd


def build_env(env: dict[str, str], port: int) -> dict[str, str]:
    """Env final do processo do runner: expande `{port}` nos VALORES (não
    nas chaves) e injeta as envs de porta quando `port > 0` e o usuário
    não as definiu explicitamente:
    - `PORT` — Node/Express/CRA/Next e afins;
    - `SERVER_PORT` — Spring Boot/Quarkus (relaxed binding lê direto,
      sem precisar de {port} no comando).
    Retorna um novo dict (não muta o original).
    """
    if port <= 0:
        return dict(env)
    out = {k: expand_port(v, port) for k, v in env.items()}
    for var in ("PORT", "SERVER_PORT"):
        if var not in out:
            out[var] = str(port)
    return out
