"""Testes do StateServer (endpoint local pro plugin de browser)."""

import json
import socket
import urllib.request

from claude_workspaces.services.state_server import StateServer


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_state_server_serve_snapshot(tmp_path):
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({
            "ports": {
                "4202": {
                    "workspace": "map",
                    "runner": "web",
                    "scope": "console",
                    "cwd": str(tmp_path),  # não-git → branch vazio, worktree False
                    "state": "running",
                }
            }
        })
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/state.json", timeout=5
        ) as resp:
            assert resp.status == 200
            # Sem Origin → sem ACAO (CORS só pra origens locais/extensão).
            assert resp.headers.get("Access-Control-Allow-Origin") is None
            data = json.loads(resp.read().decode("utf-8"))
        entry = data["ports"]["4202"]
        assert entry["workspace"] == "map"
        assert entry["runner"] == "web"
        assert entry["worktree"] is False
        assert "ts" in data
    finally:
        srv.stop()


def test_payload_merges_served_mismatch(tmp_path):
    """O _payload espelha o served-info (Detecção A) calculado pela thread."""
    srv = StateServer(port=_free_port())
    srv.update({"ports": {"8088": {"workspace": "ogpms", "runner": "gf",
                                   "cwd": str(tmp_path), "state": "running"}}})
    # Injeta direto o que a thread de fundo produziria.
    srv._served = {"8088": {"served_pid": 42,
                            "served_cwd": "/repo/principal",
                            "served_mismatch": True}}
    entry = srv._payload()["ports"]["8088"]
    assert entry["served_mismatch"] is True
    assert entry["served_cwd"] == "/repo/principal"


def _fake_branch_info(cwd: str) -> dict:
    repo = "/r/manager/.git" if "/manager/" in cwd else "/r/sipe/.git"
    if "editar-documento" in cwd:
        return {"branch": "fix/editar-documento", "worktree": True,
                "head_commit": "doc123", "repo": repo}
    if "filtro-ocorrencia" in cwd:
        return {"branch": "fix/filtro-ocorrencia", "worktree": True,
                "head_commit": "flt123", "repo": repo}
    return {"branch": "", "worktree": False, "head_commit": "", "repo": ""}


def test_payload_reatribui_porta_ao_runner_vivo_servido():
    """Runner morto segura a chave da porta, mas quem serve é outro worktree
    (vivo, sob chave sintética). A pill tem que mostrar o worktree servido."""
    srv = StateServer(port=_free_port())
    srv._branch_info = _fake_branch_info  # sem git de verdade
    doc = "/r/sipe.claude/sipepro_fix_editar-documento/src/web"
    flt = "/r/sipe.claude/sipepro_fix_filtro-ocorrencia/src/web"
    srv.update({"ports": {
        "3000": {"workspace": "sipepro", "runner": "web", "scope": "console",
                 "cwd": flt, "state": "exited",
                 "console_session_id": "sid-filtro",
                 "console_branch": "fix/filtro-ocorrencia"},
        "r:doc": {"workspace": "sipepro", "runner": "web", "scope": "console",
                  "cwd": doc, "state": "running",
                  "console_session_id": "sid-doc",
                  "console_branch": "fix/editar-documento"},
    }})
    srv._served = {"3000": {"served_pid": 99, "served_cwd": doc,
                            "served_mismatch": True}}
    entry = srv._payload()["ports"]["3000"]
    # Exibe o worktree REALMENTE servido (documentos), não o do runner morto.
    assert entry["branch"] == "fix/editar-documento"
    assert entry["worktree"] is True
    assert entry["head_commit"] == "doc123"
    assert entry["cwd"] == doc
    assert entry["state"] == "running"
    # Exibido == servido → sem ⚠; "ir pra sessão" aponta o console certo.
    assert entry["served_mismatch"] is False
    assert entry["console_session_id"] == "sid-doc"
    assert entry["console_branch"] == "fix/editar-documento"


def test_payload_reatribui_web_exato_nao_irmao_api():
    """Com api E web do mesmo worktree no snapshot, a porta servida pelo web
    vai pro web (cwd exato) — nunca pro api (irmão da mesma raiz)."""
    srv = StateServer(port=_free_port())
    srv._branch_info = _fake_branch_info
    web = "/r/sipe.claude/sipepro_fix_editar-documento/src/web"
    api = "/r/sipe.claude/sipepro_fix_editar-documento/src/api/src/Sipe.Api"
    srv.update({"ports": {
        "3000": {"workspace": "sipepro", "runner": "web", "scope": "console",
                 "cwd": "/r/sipe.claude/sipepro_fix_filtro-ocorrencia/src/web",
                 "state": "exited", "console_session_id": "sid-filtro"},
        "r:web": {"workspace": "sipepro", "runner": "web (5173)",
                  "scope": "console", "cwd": web, "state": "running",
                  "console_session_id": "sid-doc"},
        "r:api": {"workspace": "sipepro", "runner": "api (5000)",
                  "scope": "console", "cwd": api, "state": "running",
                  "console_session_id": "sid-doc"},
    }})
    srv._served = {"3000": {"served_pid": 1, "served_cwd": web,
                            "served_mismatch": True}}
    entry = srv._payload()["ports"]["3000"]
    assert entry["runner"] == "web (5173)"   # web exato, não o api
    assert entry["cwd"] == web
    assert entry["branch"] == "fix/editar-documento"
    assert entry["served_mismatch"] is False


def test_payload_nao_mislabela_irmao_quando_web_ausente():
    """Web (quem serve) não está no snapshot — só sobrou o api do mesmo
    worktree. A porta NÃO pode virar 'api'; cai no fallback (served_cwd) e
    mantém o ⚠ (o runner real do web não está vivo no app)."""
    srv = StateServer(port=_free_port())
    srv._branch_info = _fake_branch_info
    web = "/r/sipe.claude/sipepro_fix_editar-documento/src/web"
    api = "/r/sipe.claude/sipepro_fix_editar-documento/src/api/src/Sipe.Api"
    srv.update({"ports": {
        "3000": {"workspace": "sipepro", "runner": "web", "scope": "console",
                 "cwd": "/r/sipe.claude/sipepro_fix_filtro-ocorrencia/src/web",
                 "state": "exited", "console_session_id": "sid-filtro"},
        "r:api": {"workspace": "sipepro", "runner": "api (5000)",
                  "scope": "console", "cwd": api, "state": "running",
                  "console_session_id": "sid-doc"},
    }})
    srv._served = {"3000": {"served_pid": 1, "served_cwd": web,
                            "served_mismatch": True}}
    entry = srv._payload()["ports"]["3000"]
    assert entry["runner"] != "api (5000)"        # não mislabela o irmão
    assert entry["branch"] == "fix/editar-documento"  # verdade via served_cwd
    assert entry["cwd"] == web
    assert entry["served_mismatch"] is True       # web real não está vivo → ⚠


def test_payload_zumbi_sem_runner_usa_served_cwd():
    """Processo órfão fora dos runners do app → resolve o branch direto do
    served_cwd e mantém o ⚠ (Detecção A continua útil)."""
    srv = StateServer(port=_free_port())
    srv._branch_info = _fake_branch_info
    flt = "/r/sipe.claude/sipepro_fix_filtro-ocorrencia/src/web"
    doc = "/r/sipe.claude/sipepro_fix_editar-documento/src/web"
    srv.update({"ports": {
        "3000": {"workspace": "sipepro", "runner": "web", "scope": "console",
                 "cwd": flt, "state": "exited"},
    }})
    srv._served = {"3000": {"served_pid": 99, "served_cwd": doc,
                            "served_mismatch": True}}
    entry = srv._payload()["ports"]["3000"]
    assert entry["branch"] == "fix/editar-documento"  # via served_cwd
    assert entry["worktree"] is True
    assert entry["cwd"] == doc
    assert entry["served_mismatch"] is True            # zumbi → mantém ⚠


def test_focus_segue_o_dono_reatribuido():
    """/focus numa porta servida por outro worktree foca o console do runner
    que REALMENTE serve (bate com o que a pill mostra), não o que segurava a
    chave."""
    srv = StateServer(port=_free_port())
    web = "/r/sipe.claude/sipepro_fix_editar-documento/src/web"
    srv.update({"ports": {
        "3000": {"workspace": "sipepro", "runner": "web",
                 "cwd": "/r/sipe.claude/sipepro_fix_filtro-ocorrencia/src/web",
                 "state": "exited", "console_session_id": "sid-filtro"},
        "r:web": {"workspace": "sipepro", "runner": "web (5173)", "cwd": web,
                  "state": "running", "console_session_id": "sid-doc"},
    }})
    srv._served = {"3000": {"served_pid": 1, "served_cwd": web,
                            "served_mismatch": True}}
    focused: list[dict] = []
    srv.set_focus_callback(focused.append)
    assert srv._request_focus("/focus?port=3000") is True
    assert focused and focused[0]["console_session_id"] == "sid-doc"


def test_state_server_404_em_path_desconhecido():
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        import urllib.error
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/outra", timeout=5
            )
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_state_server_porta_ocupada_nao_explode():
    port = _free_port()
    srv1 = StateServer(port=port)
    assert srv1.start()
    try:
        srv2 = StateServer(port=port)
        assert srv2.start() is False
        assert srv2.running is False
    finally:
        srv1.stop()


def test_branch_info_em_worktree_real(tmp_path):
    """cwd que é git worktree de verdade → branch + worktree True."""
    import subprocess

    def run(args, cwd):
        subprocess.run(args, cwd=cwd, capture_output=True, check=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "config", "user.email", "t@t"], repo)
    run(["git", "config", "user.name", "t"], repo)
    (repo / "f.txt").write_text("hi")
    run(["git", "add", "f.txt"], repo)
    run(["git", "commit", "-q", "-m", "init"], repo)
    from claude_workspaces.git_worktree import add_worktree
    ok, _msg, wt = add_worktree(str(repo), "feat/x")
    assert ok

    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({"ports": {"4202": {"workspace": "w", "runner": "web",
                                       "scope": "console", "cwd": str(wt),
                                       "state": "running"}}})
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/state.json", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entry = data["ports"]["4202"]
        assert entry["worktree"] is True
        assert entry["branch"] == "feat/x"
    finally:
        srv.stop()


def test_branch_info_repo_key_consistente_entre_worktrees(tmp_path):
    """A chave `repo` (common-dir) é a MESMA pro checkout principal e pros
    worktrees do mesmo repo, e diferente entre repos — base do agrupamento
    api/web vs manager no plugin."""
    import subprocess

    def run(args, cwd):
        subprocess.run(args, cwd=cwd, capture_output=True, check=True)

    def init_repo(path):
        path.mkdir()
        run(["git", "init", "-q", "-b", "main"], path)
        run(["git", "config", "user.email", "t@t"], path)
        run(["git", "config", "user.name", "t"], path)
        (path / "f.txt").write_text("hi")
        run(["git", "add", "f.txt"], path)
        run(["git", "commit", "-q", "-m", "init"], path)

    from claude_workspaces.git_worktree import add_worktree
    repo = tmp_path / "repo"
    init_repo(repo)
    ok, _m, wt = add_worktree(str(repo), "feat/x")
    assert ok
    other = tmp_path / "other"
    init_repo(other)

    srv = StateServer(port=_free_port())
    main_repo = srv._branch_info(str(repo))["repo"]
    wt_repo = srv._branch_info(str(wt))["repo"]
    other_repo = srv._branch_info(str(other))["repo"]
    assert main_repo and main_repo == wt_repo      # worktrees do MESMO repo
    assert other_repo and other_repo != main_repo  # repo diferente


def test_open_endpoint(tmp_path, monkeypatch):
    import urllib.error

    opened: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **kw):
            opened.append(list(args))

    import claude_workspaces.services.state_server as ss
    monkeypatch.setattr("subprocess.Popen", _FakePopen)

    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({"ports": {"4202": {"cwd": str(tmp_path)}}})
        # Porta conhecida → 204 + xdg-open no cwd do snapshot.
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/open?port=4202", timeout=5
        )
        assert req.status == 204
        assert opened == [["xdg-open", str(tmp_path)]]
        # Porta desconhecida → 404, sem abrir nada.
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/open?port=9999", timeout=5
            )
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(opened) == 1
    finally:
        srv.stop()


def test_focus_endpoint():
    import urllib.error

    focused: list[dict] = []
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        srv.update({"ports": {"4202": {
            "workspace_id": "abc", "console_session_id": "sid-1",
        }}})
        # Sem callback → 404.
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/focus?port=4202", timeout=5
            )
            raise AssertionError("esperava 404 sem callback")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        srv.set_focus_callback(focused.append)
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/focus?port=4202", timeout=5
        )
        assert req.status == 204
        assert focused == [{
            "workspace_id": "abc", "console_session_id": "sid-1",
        }]
        # Porta desconhecida → 404.
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/focus?port=9999", timeout=5
            )
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def _get(url, headers=None):
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=5)


def test_payload_inclui_token_e_origin_guard():
    import urllib.error
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        with _get(f"http://127.0.0.1:{port}/state.json") as resp:
            data = json.loads(resp.read().decode())
            assert data["token"] == srv.token
            # Sem Origin (curl local) → sem header ACAO.
            assert resp.headers.get("Access-Control-Allow-Origin") is None
        # Origin local → ecoado.
        with _get(
            f"http://127.0.0.1:{port}/state.json",
            headers={"Origin": "http://localhost:4202"},
        ) as resp:
            assert resp.headers["Access-Control-Allow-Origin"] == (
                "http://localhost:4202"
            )
        # Origin da internet → 403 (evil.com não lê paths/branches/token).
        try:
            _get(
                f"http://127.0.0.1:{port}/state.json",
                headers={"Origin": "https://evil.com"},
            )
            raise AssertionError("esperava 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # Host estranho (DNS rebinding) → 403.
        try:
            _get(
                f"http://127.0.0.1:{port}/state.json",
                headers={"Host": "evil.com"},
            )
            raise AssertionError("esperava 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.stop()


class _FakeHub:
    def __init__(self):
        import queue
        self.writes = []
        self._q = queue.Queue()
        self._ring = b"backlog!"

    def replay(self, sid):
        return self._ring

    def subscribe(self, sid):
        return self._q

    def unsubscribe(self, sid, q):
        pass

    def write(self, sid, data):
        self.writes.append((sid, data))
        return True

    def size(self, sid):
        return (132, 43)


def test_console_endpoints_token_e_input():
    import urllib.error
    import urllib.request
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    hub = _FakeHub()
    srv.set_hub(hub)
    try:
        srv.update({"ports": {"4202": {
            "workspace": "map", "runner": "web", "runner_id": "r1",
            "console_session_id": "sid-1", "cwd": "",
        }}})
        # Token errado → 403.
        try:
            _get(f"http://127.0.0.1:{port}/console?port=4202&token=x")
            raise AssertionError("esperava 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # Página ok com token certo (contém xterm + tabs).
        with _get(
            f"http://127.0.0.1:{port}/console?port=4202&token={srv.token}"
        ) as resp:
            html = resp.read().decode()
            assert "xterm.js" in html and "Claude" in html
            # Geometria do PTY (hub.size) injetada — sem fit-de-janela.
            assert 'Number("132")' in html and 'Number("43")' in html
            assert "FitAddon" not in html
        # /console/size → geometria do PTY de origem.
        import json as _json
        with _get(
            f"http://127.0.0.1:{port}/console/size?port=4202&token={srv.token}"
        ) as resp:
            assert _json.loads(resp.read()) == {"cols": 132, "rows": 43}
        # Input → hub.write com o sid.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/console/input?port=4202&token={srv.token}",
            data=b"ls\r",
            method="POST",
        )
        assert urllib.request.urlopen(req, timeout=5).status == 204
        assert hub.writes == [("sid-1", b"ls\r")]
        # Porta sem console (workspace-scope) → 404.
        srv.update({"ports": {"3000": {"runner": "web", "runner_id": "r2"}}})
        try:
            _get(f"http://127.0.0.1:{port}/console?port=3000&token={srv.token}")
            raise AssertionError("esperava 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_console_tabs_incluem_runner_sem_porta():
    """Runner de console SEM porta (chave sintética r:<id>) deve virar aba no
    espelho — antes só runners com porta no snapshot apareciam."""
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    srv.set_hub(_FakeHub())
    try:
        srv.update({"ports": {
            # aba do Claude (porta detectada do vite, p.ex.)
            "3000": {"workspace": "sipepro", "runner": "web", "runner_id": "rw",
                     "console_session_id": "sid-1", "cwd": ""},
            # runner sem porta → chave sintética
            "r:ra": {"workspace": "sipepro", "runner": "api (5000)",
                     "runner_id": "ra", "console_session_id": "sid-1", "cwd": ""},
        }})
        with _get(
            f"http://127.0.0.1:{port}/console?port=3000&token={srv.token}"
        ) as resp:
            html = resp.read().decode()
        assert "api (5000)" in html        # a aba do runner sem porta aparece
        assert '"port": "r:ra"' in html     # endereçada pela chave sintética
        assert '"target": "runner"' in html
    finally:
        srv.stop()


def test_static_whitelist_e_traversal():
    import urllib.error
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    try:
        with _get(f"http://127.0.0.1:{port}/static/xterm.js") as resp:
            assert resp.status == 200
            assert "javascript" in resp.headers["Content-Type"]
        for bad in ("/static/../models.py", "/static/nao-existe.js"):
            try:
                _get(f"http://127.0.0.1:{port}{bad}")
                raise AssertionError("esperava 404")
            except urllib.error.HTTPError as e:
                assert e.code == 404
    finally:
        srv.stop()


def test_runner_restart_endpoint():
    import urllib.error
    port = _free_port()
    srv = StateServer(port=port)
    assert srv.start()
    restarted: list[dict] = []
    srv.set_restart_callback(restarted.append)
    try:
        srv.update({"ports": {"4202": {
            "workspace_id": "w1", "runner_id": "r1",
        }}})
        assert _get(
            f"http://127.0.0.1:{port}/runner/restart?port=4202&token={srv.token}"
        ).status == 204
        assert restarted[0]["runner_id"] == "r1"
        try:
            _get(f"http://127.0.0.1:{port}/runner/restart?port=4202&token=x")
            raise AssertionError("esperava 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.stop()


def test_console_hub_pubsub():
    from claude_workspaces.services.console_hub import ConsoleHub

    class _FakeSession:
        def __init__(self):
            self.written = []

        def write(self, data):
            self.written.append(data)

    class _FakeTerm:
        def __init__(self):
            self.session = _FakeSession()

    hub = ConsoleHub()
    term = _FakeTerm()
    hub.attach("sid-1", term)
    q = hub.subscribe("sid-1")
    hub.publish("sid-1", b"hello ")
    hub.publish("sid-1", b"world")
    assert q.get_nowait() == b"hello "
    assert q.get_nowait() == b"world"
    assert hub.replay("sid-1") == b"hello world"
    assert hub.write("sid-1", b"ls\r") is True
    assert term.session.written == [b"ls\r"]
    hub.rekey("sid-1", "sid-2")
    assert hub.replay("sid-2") == b"hello world"
    assert hub.write("sid-2", b"x") is True
    hub.unsubscribe("sid-2", q)
