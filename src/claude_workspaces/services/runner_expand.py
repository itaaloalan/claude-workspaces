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
