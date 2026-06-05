"""Expansão do placeholder {port} nos campos de um runner.

A expansão acontece SÓ na hora de rodar (runner_widget._spawn e fluxo de
browser) — o que se persiste é a `port` numérica; os comandos guardam
`{port}` literal.
"""

from __future__ import annotations


def expand_port(text: str, port: int) -> str:
    """Substitui `{port}` por `port` em `text`. `port <= 0` → intacto.

    Usa str.replace, NUNCA str.format — comandos shell têm `{}` legítimos
    (awk '{print}', ${VAR}, JSON inline) que o format() quebraria.
    """
    if port <= 0:
        return text
    return text.replace("{port}", str(port))


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
    nas chaves) e injeta `PORT=<port>` quando `port > 0` e o usuário não
    definiu PORT explicitamente. Retorna um novo dict (não muta o original).
    """
    if port <= 0:
        return dict(env)
    out = {k: expand_port(v, port) for k, v in env.items()}
    if "PORT" not in out:
        out["PORT"] = str(port)
    return out
