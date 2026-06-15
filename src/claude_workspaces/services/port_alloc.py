"""Alocação de portas pra runners console-scoped.

Quando o mesmo runner roda em vários consoles/worktrees em paralelo, cada
cópia precisa de uma porta própria — a partir da porta base do runner
workspace-scoped, a cópia ganha a próxima livre (pulando as já reservadas
por outros runners do workspace e as ocupadas no SO via bind test).
"""

from __future__ import annotations

import socket


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """True se conseguimos dar bind em (host, port) — qualquer OSError
    conta como ocupada. Best-effort (TOCTOU inevitável): o objetivo é só
    pular colisões óbvias, não garantir reserva."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def next_free_port(
    base: int,
    used: set[int],
    *,
    host: str = "127.0.0.1",
    max_tries: int = 200,
    probe_os: bool = True,
) -> int:
    """Primeira porta >= base que não está em `used` (e, se `probe_os`,
    nem ocupada no SO via bind test).

    `base == 0` (runner sem porta) → retorna 0 sem testar nada.

    `probe_os=False` torna a alocação DETERMINÍSTICA — depende só de `used`,
    não do estado de execução do SO. Usado na cópia pra console: a porta de
    cada worktree é função da contagem de cópias já existentes (1ª = base,
    2ª = base+1, …), e não muda só porque o runner do workspace está rodando
    na base naquele instante (o bind test bumparia a 1ª cópia pra base+1).
    """
    if base <= 0:
        return 0
    for port in range(base, min(base + max_tries, 65536)):
        if port in used:
            continue
        if not probe_os or is_port_free(port, host=host):
            return port
    raise RuntimeError(
        f"nenhuma porta livre encontrada a partir de {base} "
        f"({max_tries} tentativas)"
    )


def reserved_console_ports(
    workspace,
    open_session_ids: set[str] | None = None,
) -> set[int]:
    """Portas reservadas pelas cópias CONSOLE-scoped do workspace.

    Runners workspace-scoped NÃO reservam porta na alocação de cópias —
    eles são alternativas (ex: api jdk25 e jdk8 na mesma base) e, se um
    estiver rodando, o bind test já detecta a porta ocupada. Sem isso,
    dois runners workspace com a mesma base faziam a 1ª cópia sempre
    incrementar, violando a regra "sem cópia de console → mesma porta".

    `open_session_ids`: quando fornecido, somente cópias cujo
    `console_session_id` esteja no conjunto são contadas. Cópias de
    consoles **fechados** (órfãos) ficam fora — suas portas são
    reutilizáveis e não devem empurrar novas cópias pra base+N. Quando
    `None` (padrão), todas as cópias contam (comportamento legado).
    """
    return {
        r.port
        for r in workspace.runners
        if getattr(r, "port", 0) > 0
        and (sid := (r.console_session_id or ""))
        and (open_session_ids is None or sid in open_session_ids)
    }


def used_ports_in_workspace(workspace, *, exclude_id: str = "") -> set[int]:
    """Portas já reservadas pelos runners do workspace (todos os escopos).

    `exclude_id` ignora um runner específico — usado pra NÃO reservar a
    porta do runner de ORIGEM ao copiar pro console: sem nenhuma cópia
    existente (e porta livre no SO), a 1ª cópia fica com a própria base;
    o bind test cuida do caso "origem rodando" (porta ocupada → base+1).
    """
    return {
        r.port
        for r in workspace.runners
        if getattr(r, "port", 0) > 0 and r.id != exclude_id
    }
