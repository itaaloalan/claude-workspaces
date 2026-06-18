import uuid
from dataclasses import asdict, dataclass, field


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class RunnerConfig:
    """Runner = processo de longa duração do workspace (web/api/glassfish/…).

    Comandos rodam via `bash -lc <cmd>` para herdar aliases/PATH do shell de
    login. `stop_cmd`/`restart_cmd` vazios caem em fallbacks: stop = SIGTERM
    no process group; restart = stop + start.
    """
    name: str = ""
    start_cmd: str = ""
    stop_cmd: str = ""
    restart_cmd: str = ""
    cwd: str = ""                       # vazio → primeira pasta do workspace
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True                # incluído no "Rodar todos"
    # Abre o browser do sistema na URL detectada na stdout (ex:
    # "Local: http://localhost:3000", "Listening on port 8080"). Quando
    # `browser_url` está preenchido, usa o valor direto em vez de
    # detectar. URL é aberta uma única vez por start.
    open_browser_on_ready: bool = False
    browser_url: str = ""               # override manual; vazio = autodetect
    # Regex (case-insensitive) que precisa casar na stdout antes do
    # browser abrir. Vazio = abre na primeira URL detectada (comportamento
    # antigo). Útil pra servers em que a porta sobe antes do deploy
    # terminar — ex: Glassfish, onde a URL final só é válida após
    # "Application [ogpms] deployed successfully".
    ready_pattern: str = ""
    # Porta base do runner. 0 = runner sem porta (expansão desligada).
    # Quando > 0: `{port}` é substituído nos comandos/browser_url/env na
    # hora de rodar, e `PORT=<porta>` é injetada no env do processo (sem
    # sobrescrever um PORT explícito). Cópias console-scoped ganham a
    # próxima porta livre a partir da base (ver services/port_alloc.py).
    port: int = 0
    # Participa do "⬇ Subir stack" (cópia automática pro console)?
    # Workspaces com muitos runners sobem só os marcados (ex: map copia
    # web + api; jdk8/history/coletor ficam de fora). Cópia manual via
    # "↗ Copiar do workspace" ignora a flag.
    include_in_stack: bool = True
    # Escopo do runner. Vazio = pertence ao workspace (comportamento
    # antigo, aparece no painel inferior do workspace). Quando preenchido
    # com o session_id de um console Claude, o runner pertence àquele
    # console — só aparece dentro do painel embutido daquela aba, permite
    # rodar várias instâncias do mesmo serviço com branch/porta diferentes
    # em consoles paralelos.
    console_session_id: str = ""
    # Metadata da sessão Claude que originou este runner (via "Gerar com
    # Claude"). Permite retomar a conversa de geração depois pra pedir
    # ajustes — preenchido em `runners_io.import_runners` quando o reload
    # vem do rascunho de runner-gen. Não é portável: removido no export.
    gen_session_id: str = ""
    gen_cwd: str = ""
    # Último diretório apontado pelo usuário via chip 📁 ("" = padrão).
    # Persiste o apontamento entre restarts do app — "manter o último
    # executado". Path da máquina: removido no export, igual aos gen_*.
    last_cwd: str = ""
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunnerConfig":
        env_raw = data.get("env") or {}
        env = {str(k): str(v) for k, v in env_raw.items()} if isinstance(env_raw, dict) else {}
        try:
            port = int(data.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        return cls(
            name=str(data.get("name", "")),
            start_cmd=str(data.get("start_cmd", "")),
            stop_cmd=str(data.get("stop_cmd", "")),
            restart_cmd=str(data.get("restart_cmd", "")),
            cwd=str(data.get("cwd", "")),
            env=env,
            enabled=bool(data.get("enabled", True)),
            open_browser_on_ready=bool(data.get("open_browser_on_ready", False)),
            browser_url=str(data.get("browser_url", "")),
            ready_pattern=str(data.get("ready_pattern", "")),
            port=port,
            include_in_stack=bool(data.get("include_in_stack", True)),
            console_session_id=str(data.get("console_session_id", "")),
            gen_session_id=str(data.get("gen_session_id", "")),
            gen_cwd=str(data.get("gen_cwd", "")),
            last_cwd=str(data.get("last_cwd", "")),
            id=str(data.get("id") or _new_id()),
        )


@dataclass
class Workspace:
    name: str
    folders: list[str] = field(default_factory=list)
    description: str = ""
    id: str = field(default_factory=_new_id)
    # Overrides do LaunchClaudeDialog. Quando None/vazio, usa o valor
    # global das Configurações. Defaults pra preservar comportamento
    # antigo de workspaces criados antes desses campos existirem.
    branch_prefix: str = ""           # "" → settings.branch_prefix
    default_isolate_worktree: bool | None = None
    default_create_new_branch: bool | None = None
    runners: list[RunnerConfig] = field(default_factory=list)
    # Workspaces fixados aparecem na seção "FIXADOS" no topo da sidebar
    # (saem da lista principal pra não duplicar visualmente).
    pinned: bool = False
    # Workspaces minimizados saem da lista da sidebar e viram um chip na
    # faixa "Minimizados" no rodapé — clicar no chip restaura. Independente
    # de pinned: minimizado ganha prioridade (não aparece como card).
    minimized: bool = False
    # Ícone custom do workspace na sidebar (caminho pra um arquivo de imagem
    # — o "ícone real do projeto", ex.: favicon/logo). "" = ícone de pasta
    # padrão. Detectado via services.project_icon ou escolhido à mão.
    icon: str = ""
    # Servidores MCP (de ~/.claude.json) que ESTE workspace carrega ao lançar
    # o Claude (via --mcp-config --strict-mcp-config). Controla memória: sem
    # isto toda sessão sobe TODOS os MCP globais. Semântica:
    #   None  → auto-inferir pelo nome/pastas (services.mcp_scope)
    #   []    → nenhum MCP (strict vazio)
    #   [...] → exatamente esses
    mcp_servers: list[str] | None = None

    @property
    def primary_folder(self) -> str | None:
        return self.folders[0] if self.folders else None

    @property
    def extra_folders(self) -> list[str]:
        return self.folders[1:] if len(self.folders) > 1 else []

    def launch_paths(self) -> tuple[str, list[str]]:
        """Decide o cwd e as pastas extras pra --add-dir.

        Primeira pasta vira cwd; demais entram como --add-dir. Isso
        garante que o contexto do Claude seja exatamente o conjunto
        de pastas escolhido pelo usuário, sem vazar irmãos não-listados
        (problema do colapso automático pro pai comum, que dava acesso
        a tudo sob o diretório-mãe mesmo sem o usuário pedir).

        Se você quiser que o Claude veja o pai inteiro, basta criar um
        workspace com a pasta-pai como única entrada.
        """
        if not self.folders:
            raise ValueError("Workspace sem pastas")
        return self.folders[0], self.folders[1:]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        # default_*_*: aceita True/False/None do JSON; campo ausente vira None
        isolate = data.get("default_isolate_worktree")
        if isolate is not None and not isinstance(isolate, bool):
            isolate = None
        create_branch = data.get("default_create_new_branch")
        if create_branch is not None and not isinstance(create_branch, bool):
            create_branch = None
        runners_raw = data.get("runners") or []
        runners = [
            RunnerConfig.from_dict(r) for r in runners_raw
            if isinstance(r, dict)
        ]
        return cls(
            name=data["name"],
            folders=list(data.get("folders", [])),
            description=data.get("description", ""),
            id=str(data.get("id") or _new_id()),
            branch_prefix=str(data.get("branch_prefix") or ""),
            default_isolate_worktree=isolate,
            default_create_new_branch=create_branch,
            runners=runners,
            pinned=bool(data.get("pinned", False)),
            minimized=bool(data.get("minimized", False)),
            icon=str(data.get("icon") or ""),
            mcp_servers=(
                list(data["mcp_servers"])
                if isinstance(data.get("mcp_servers"), list)
                else None
            ),
        )
