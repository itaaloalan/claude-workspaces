"""Testes do remapeamento de porta dos runners ({port} + alocação)."""

import socket

import pytest

from claude_workspaces.models import RunnerConfig, Workspace
from claude_workspaces.services.port_alloc import (
    is_port_free,
    next_free_port,
    used_ports_in_workspace,
)
from claude_workspaces.services.runner_expand import build_env, expand_port

# ---- expand_port -----------------------------------------------------------


def test_expand_port_substitui_placeholder():
    assert expand_port("npm run dev --port {port}", 3001) == (
        "npm run dev --port 3001"
    )


def test_expand_port_multiplas_ocorrencias():
    cmd = "kill $(lsof -ti:{port}); serve -p {port}"
    assert expand_port(cmd, 8081) == "kill $(lsof -ti:8081); serve -p 8081"


def test_expand_port_nao_quebra_chaves_de_shell():
    # awk '{print}' e ${VAR} têm {} legítimos — só {port} pode mudar.
    cmd = "ps aux | awk '{print $1}' && echo ${HOME} --port {port}"
    assert expand_port(cmd, 9000) == (
        "ps aux | awk '{print $1}' && echo ${HOME} --port 9000"
    )


def test_expand_port_zero_eh_noop():
    cmd = "serve --port {port}"
    assert expand_port(cmd, 0) == cmd


# ---- build_env -------------------------------------------------------------


def test_build_env_expande_valores_e_injeta_port():
    env = build_env({"API_URL": "http://localhost:{port}/api"}, 8081)
    assert env["API_URL"] == "http://localhost:8081/api"
    assert env["PORT"] == "8081"
    # Spring Boot lê SERVER_PORT direto (relaxed binding).
    assert env["SERVER_PORT"] == "8081"


def test_build_env_preserva_port_do_usuario():
    env = build_env({"PORT": "9999"}, 8081)
    assert env["PORT"] == "9999"
    assert env["SERVER_PORT"] == "8081"


def test_build_env_preserva_server_port_do_usuario():
    env = build_env({"SERVER_PORT": "7777"}, 8081)
    assert env["SERVER_PORT"] == "7777"
    assert env["PORT"] == "8081"


def test_build_env_port_do_usuario_com_placeholder():
    env = build_env({"PORT": "{port}"}, 8081)
    # O placeholder do usuário expande; não é sobrescrito pela injeção.
    assert env["PORT"] == "8081"


def test_build_env_nao_expande_chaves():
    env = build_env({"X_{port}": "v"}, 8081)
    assert "X_{port}" in env


def test_build_env_port_zero_eh_noop():
    original = {"A": "{port}"}
    env = build_env(original, 0)
    assert env == {"A": "{port}"}
    assert "PORT" not in env


def test_build_env_nao_muta_original():
    original = {"A": "{port}"}
    build_env(original, 8081)
    assert original == {"A": "{port}"}


# ---- next_free_port --------------------------------------------------------


def test_next_free_port_pula_usadas(monkeypatch):
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free", lambda p, host="127.0.0.1": True
    )
    assert next_free_port(3000, {3000}) == 3001
    assert next_free_port(3000, {3000, 3001}) == 3002
    assert next_free_port(3000, set()) == 3000


def test_next_free_port_pula_ocupadas_no_so(monkeypatch):
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": p != 3000,
    )
    assert next_free_port(3000, set()) == 3001


def test_next_free_port_base_zero():
    assert next_free_port(0, {3000}) == 0


def test_next_free_port_probe_os_false_ignora_so(monkeypatch):
    """Determinístico: com probe_os=False a porta ocupada no SO é reusada;
    só `used` faz pular. É o modo da cópia pra console."""
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": False,  # tudo "ocupado" no SO
    )
    # base livre em `used` → reusa, mesmo "ocupada" no SO.
    assert next_free_port(3000, set(), probe_os=False) == 3000
    # com a base reservada por uma cópia, incrementa determinístico.
    assert next_free_port(3000, {3000}, probe_os=False) == 3001
    assert next_free_port(3000, {3000, 3001}, probe_os=False) == 3002


def test_next_free_port_estoura(monkeypatch):
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": False,
    )
    with pytest.raises(RuntimeError):
        next_free_port(3000, set(), max_tries=5)


def test_is_port_free_real():
    # Ocupa uma porta efêmera de verdade e confere o bind test.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert is_port_free(port) is False
    # Liberada após o close.
    assert is_port_free(port) is True


# ---- used_ports_in_workspace ------------------------------------------------


def test_used_ports_in_workspace():
    ws = Workspace(
        name="w",
        runners=[
            RunnerConfig(name="api", port=8080),
            RunnerConfig(name="web", port=3000),
            RunnerConfig(name="semporta", port=0),
        ],
    )
    assert used_ports_in_workspace(ws) == {8080, 3000}


def test_used_ports_exclui_origem():
    api = RunnerConfig(name="api", port=8080)
    ws = Workspace(
        name="w",
        runners=[api, RunnerConfig(name="web", port=3000)],
    )
    assert used_ports_in_workspace(ws, exclude_id=api.id) == {3000}


def test_primeira_copia_usa_base_quando_livre(monkeypatch):
    """Sem cópias de console e porta livre no SO, a 1ª cópia fica com a
    própria base; com uma cópia já na base, incrementa."""
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": True,
    )
    api = RunnerConfig(name="api", port=8080)
    ws = Workspace(name="w", runners=[api])
    # used SEM a porta da origem → base é alocável.
    used = used_ports_in_workspace(ws, exclude_id=api.id)
    assert next_free_port(api.port, used) == 8080
    # Com uma cópia console já na 8080, a próxima vai pra 8081.
    ws.runners.append(
        RunnerConfig(name="api", port=8080, console_session_id="sid-1")
    )
    used = used_ports_in_workspace(ws, exclude_id=api.id)
    assert next_free_port(api.port, used) == 8081


# ---- modelo -----------------------------------------------------------------


def test_runner_config_port_roundtrip():
    r = RunnerConfig(name="api", port=8080)
    clone = RunnerConfig.from_dict(r.to_dict())
    assert clone.port == 8080


def test_runner_config_port_default_zero():
    assert RunnerConfig().port == 0
    assert RunnerConfig.from_dict({"name": "x"}).port == 0


def test_runner_config_port_parse_string_e_invalido():
    assert RunnerConfig.from_dict({"port": "3000"}).port == 3000
    assert RunnerConfig.from_dict({"port": "abc"}).port == 0
    assert RunnerConfig.from_dict({"port": None}).port == 0


# ---- wrap_with_node_bootstrap ------------------------------------------------


def test_bootstrap_prefixa_o_comando():
    from claude_workspaces.services.runner_expand import wrap_with_node_bootstrap

    out = wrap_with_node_bootstrap("npm start")
    assert out.endswith("npm start")
    assert "package.json" in out and "node_modules" in out
    assert "pnpm-lock.yaml" in out and "yarn.lock" in out
    # Falha do install impede o start (&&).
    assert "fi && npm start" in out


def test_bootstrap_comando_vazio_intacto():
    from claude_workspaces.services.runner_expand import wrap_with_node_bootstrap

    assert wrap_with_node_bootstrap("") == ""
    assert wrap_with_node_bootstrap("   ") == "   "


# ---- apply_port_arg ----------------------------------------------------------


def test_apply_port_npm_start():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("npm start", 4202) == "npm start -- --port 4202"
    assert apply_port_arg("npm run dev", 4202) == "npm run dev -- --port 4202"


def test_apply_port_npm_ja_com_separador():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("npm start -- --open", 4202) == (
        "npm start -- --open --port 4202"
    )


def test_apply_port_encadeado_ultimo_segmento():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("node pre.js && npm start", 4202) == (
        "node pre.js && npm start -- --port 4202"
    )


def test_apply_port_ng_serve_ultima_vence():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("ng serve --port 4201", 4202) == (
        "ng serve --port 4201 --port 4202"
    )


def test_apply_port_vite_e_next():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("vite", 5174) == "vite --port 5174"
    assert apply_port_arg("npx vite dev", 5174) == "npx vite dev --port 5174"
    assert apply_port_arg("next dev", 3001) == "next dev -p 3001"


def test_apply_port_yarn_e_pnpm():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("yarn start", 4202) == "yarn start --port 4202"
    # pnpm (v7+) repassa args sem `--`; com `--` ele poluía os args do
    # script (`vite -- --port`) e a porta era ignorada. Sem `--`, igual yarn.
    assert apply_port_arg("pnpm dev", 4202) == "pnpm dev --port 4202"
    assert apply_port_arg("pnpm run dev", 4202) == "pnpm run dev --port 4202"


def test_apply_port_pnpm_vite_nao_insere_dash_dash():
    """Regressão: `pnpm dev` (script = vite) precisa virar `pnpm dev --port N`
    e NUNCA `pnpm dev -- --port N` — senão vira `vite -- --port N` e o vite
    ignora a porta, caindo na 3000 do config ('Port 3000 already in use')."""
    from claude_workspaces.services.runner_expand import apply_port_arg

    out = apply_port_arg("pnpm dev", 3001)
    assert out == "pnpm dev --port 3001"
    assert " -- " not in out


def test_apply_port_nao_reconhecido():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("mvn spring-boot:run", 8092) is None
    assert apply_port_arg("python coletor.py", 1972) is None
    assert apply_port_arg("", 4202) is None
    assert apply_port_arg("npm start", 0) is None


# ---- expand_port_refs ----------------------------------------------------------


def test_port_ref_resolve_vizinho():
    from claude_workspaces.services.runner_expand import expand_port_refs

    ports = {"api jdk 25": 8096, "web": 4202}
    assert expand_port_refs(
        "http://localhost:{port:api jdk 25}/api", ports
    ) == "http://localhost:8096/api"


def test_port_ref_case_insensitive_e_trim():
    from claude_workspaces.services.runner_expand import expand_port_refs

    assert expand_port_refs("{port: API JDK 25 }", {"api jdk 25": 8096}) == "8096"


def test_port_ref_desconhecido_fica_intacto():
    from claude_workspaces.services.runner_expand import expand_port_refs

    assert expand_port_refs("{port:nao-existe}", {"api": 8080}) == "{port:nao-existe}"
    assert expand_port_refs("{port:api}", {"api": 0}) == "{port:api}"


def test_port_ref_sem_placeholder_eh_noop():
    from claude_workspaces.services.runner_expand import expand_port_refs

    assert expand_port_refs("npm start", {"api": 8080}) == "npm start"
    assert expand_port_refs("", {"api": 8080}) == ""


def test_port_ref_prefixo_resolve_variante():
    from claude_workspaces.services.runner_expand import expand_port_refs

    # Sem nome exato "api", cai pro prefixo de palavra: resolve a variante de
    # api presente no escopo (jdk8 OU jdk 25), pro stack web nao precisar saber
    # qual o console escolheu.
    assert expand_port_refs("{port:api}", {"api jdk8": 8091, "web": 4201}) == "8091"
    assert expand_port_refs("{port:api}", {"api jdk 25": 8092}) == "8092"
    # Variantes alternativas dividem a mesma porta -> contam como uma.
    assert expand_port_refs("{port:api}", {"api jdk 25": 8093, "api jdk8": 8093}) == "8093"
    # Prefixo ambiguo (portas distintas) -> fica intacto.
    assert expand_port_refs("{port:api}", {"api jdk8": 8091, "api jdk 25": 8092}) == "{port:api}"
    # Nome exato tem prioridade sobre o prefixo.
    assert expand_port_refs("{port:api}", {"api": 9000, "api jdk8": 8091}) == "9000"
    # Prefixo nao casa pedaco de palavra (evita "api" casar "apiserver").
    assert expand_port_refs("{port:api}", {"apiserver": 8080}) == "{port:api}"


# ---- include_in_stack ----------------------------------------------------------


def test_include_in_stack_default_true_e_roundtrip():
    assert RunnerConfig().include_in_stack is True
    assert RunnerConfig.from_dict({"name": "x"}).include_in_stack is True
    r = RunnerConfig(name="coletor", include_in_stack=False)
    assert RunnerConfig.from_dict(r.to_dict()).include_in_stack is False


# ---- reserved_console_ports ----------------------------------------------------


def test_reserved_console_ports_so_copias_de_console():
    from claude_workspaces.services.port_alloc import reserved_console_ports

    ws = Workspace(
        name="w",
        runners=[
            RunnerConfig(name="api jdk 25", port=8091),
            RunnerConfig(name="api jdk8", port=8091),
            RunnerConfig(name="api jdk 25", port=8092, console_session_id="s1"),
            RunnerConfig(name="semporta", port=0, console_session_id="s1"),
        ],
    )
    assert reserved_console_ports(ws) == {8092}


def test_irmaos_workspace_na_mesma_base_nao_reservam(monkeypatch):
    """Map: api jdk25 e jdk8 ambos base 8091 — sem nenhuma cópia de
    console (e porta livre), a 1ª cópia usa a base; só cópias de console
    fazem incrementar."""
    from claude_workspaces.services.port_alloc import reserved_console_ports

    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": True,
    )
    ws = Workspace(
        name="map",
        runners=[
            RunnerConfig(name="api jdk 25", port=8091),
            RunnerConfig(name="api jdk8", port=8091),
        ],
    )
    assert next_free_port(8091, reserved_console_ports(ws)) == 8091
    # Cópia de console na 8091 → próxima vai pra 8092.
    ws.runners.append(
        RunnerConfig(name="api jdk 25", port=8091, console_session_id="s1")
    )
    assert next_free_port(8091, reserved_console_ports(ws)) == 8092


def test_porta_por_worktree_deterministica_com_workspace_rodando(monkeypatch):
    """Cenário do usuário: api do workspace na 8080 RODANDO; cada worktree
    que sobe a stack ganha porta determinística — 1 worktree usa a base
    (= porta do workspace), worktrees seguintes incrementam. O bind test
    não interfere (probe_os=False)."""
    from claude_workspaces.services.port_alloc import reserved_console_ports

    # SO reporta a base ocupada (workspace api rodando nela).
    monkeypatch.setattr(
        "claude_workspaces.services.port_alloc.is_port_free",
        lambda p, host="127.0.0.1": p != 8080,
    )
    api = RunnerConfig(name="api", port=8080)
    ws = Workspace(name="sipe", runners=[api])

    # Worktree A: 1ª cópia reusa a base mesmo com o workspace rodando nela.
    port_a = next_free_port(8080, reserved_console_ports(ws), probe_os=False)
    assert port_a == 8080
    ws.runners.append(
        RunnerConfig(name="api", port=port_a, console_session_id="A")
    )

    # Worktree B: porta diferente da do A.
    port_b = next_free_port(8080, reserved_console_ports(ws), probe_os=False)
    assert port_b == 8081
    ws.runners.append(
        RunnerConfig(name="api", port=port_b, console_session_id="B")
    )

    # Worktree C: incrementa de novo — três worktrees, três portas.
    port_c = next_free_port(8080, reserved_console_ports(ws), probe_os=False)
    assert port_c == 8082
    assert len({port_a, port_b, port_c}) == 3


def test_reserved_console_ports_orfaos_nao_reservam():
    """Cenário do print: sem nenhum console aberto, cópias de consoles
    FECHADOS (órfãos) não devem reservar porta — a 1ª cópia nova volta pra
    base."""
    from claude_workspaces.services.port_alloc import reserved_console_ports

    ws = Workspace(
        name="sipepro",
        runners=[
            RunnerConfig(name="api", port=5000),
            RunnerConfig(name="web", port=3000),
            # Órfão A — console já fechado.
            RunnerConfig(name="api", port=5000, console_session_id="closed-A"),
            RunnerConfig(name="web", port=3000, console_session_id="closed-A"),
            # Órfão B — outro console fechado, ganhou base+1 na época.
            RunnerConfig(name="api", port=5001, console_session_id="closed-B"),
            RunnerConfig(name="web", port=3001, console_session_id="closed-B"),
        ],
    )

    # Sem provider (None) → comportamento legado: todos reservam.
    assert reserved_console_ports(ws) == {5000, 3000, 5001, 3001}

    # Com open_session_ids vazio (nenhum console aberto) → nada reservado.
    assert reserved_console_ports(ws, open_session_ids=set()) == set()

    # 1ª cópia nova volta pra base mesmo com os órfãos em workspaces.json.
    assert (
        next_free_port(5000, reserved_console_ports(ws, open_session_ids=set()), probe_os=False)
        == 5000
    )
    assert (
        next_free_port(3000, reserved_console_ports(ws, open_session_ids=set()), probe_os=False)
        == 3000
    )


def test_reserved_console_ports_orfaos_nao_bloqueiam_abertos():
    """Com 1 console aberto (sid "open-C") contendo a porta base, a próxima
    cópia vai pra base+1 — a filtragem não quebra o caso legítimo."""
    from claude_workspaces.services.port_alloc import reserved_console_ports

    ws = Workspace(
        name="sipepro",
        runners=[
            RunnerConfig(name="api", port=5000),
            # Cópia de console ABERTO.
            RunnerConfig(name="api", port=5000, console_session_id="open-C"),
            # Órfão — fechado.
            RunnerConfig(name="api", port=5001, console_session_id="closed-D"),
        ],
    )

    open_ids = {"open-C"}
    assert reserved_console_ports(ws, open_session_ids=open_ids) == {5000}
    # Próxima cópia nova: pula 5000 (open-C reserva), vai pra 5001 — mas
    # closed-D (5001) não reserva, então 5001 está livre.
    assert (
        next_free_port(5000, reserved_console_ports(ws, open_ids), probe_os=False)
        == 5001
    )
