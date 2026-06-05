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
    assert apply_port_arg("pnpm dev", 4202) == "pnpm dev -- --port 4202"


def test_apply_port_nao_reconhecido():
    from claude_workspaces.services.runner_expand import apply_port_arg

    assert apply_port_arg("mvn spring-boot:run", 8092) is None
    assert apply_port_arg("python coletor.py", 1972) is None
    assert apply_port_arg("", 4202) is None
    assert apply_port_arg("npm start", 0) is None
