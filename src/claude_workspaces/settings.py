import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces"


def settings_file() -> Path:
    return config_dir() / "settings.json"


# Liga/desliga o OpenCode como opção de backend na UI. False = só Claude.
# "por enquanto" — flip pra True restaura o menu de backend em todo lugar.
OPENCODE_ENABLED = False


@dataclass
class Settings:
    # --- Backend: "claude" ou "opencode" ---
    ai_backend: str = "claude"

    # --- Claude CLI ---
    claude_command: str = "claude"
    claude_extra_args: list[str] = field(default_factory=list)
    # Flags injetadas em toda sessão Claude lançada pelo app (console embutido,
    # terminal externo, resume, runner-gen). Vazio = não passa a flag, deixando
    # o Claude usar o default dele/config global do usuário.
    # `claude_permission_mode`: --permission-mode <mode>. Valores aceitos pelo
    #     CLI: "default", "acceptEdits", "plan", "bypassPermissions", "auto",
    #     "dontAsk". Aplica no startup, mas o usuário ainda pode trocar via
    #     Shift+Tab depois (assim como o popup de modos faz).
    # `claude_effort`: --effort <low|medium|high|xhigh|max>. Vazio = default.
    # `claude_allowed_tools` / `claude_disallowed_tools`: lista CSV ou separada
    #     por espaço de tool specs (ex.: "Bash(git *) Edit"). Passa pra
    #     --allowedTools / --disallowedTools.
    claude_permission_mode: str = ""
    claude_effort: str = ""
    claude_allowed_tools: str = ""
    claude_disallowed_tools: str = ""

    # --- opencode CLI ---
    opencode_command: str = "opencode"
    opencode_extra_args: list[str] = field(default_factory=list)
    opencode_model: str = ""
    opencode_agent: str = ""
    terminal_command: str = "konsole"
    shell_command: str = ""  # "" = autodetect from /etc/passwd (login shell)
    vscode_command: str = "code"
    # Comando usado pelo menu de contexto do painel Arquivos pra abrir/editar
    # um arquivo individual. Default "code" (VS Code), mas configurável pra
    # qualquer editor que aceite `<cmd> <arquivo>` (ex.: "subl", "gedit",
    # "code -r", "nvim" num terminal, etc.).
    file_open_command: str = "code"
    intellij_command: str = "idea"
    webstorm_command: str = "webstorm"
    pycharm_command: str = "pycharm"
    rider_command: str = "rider"
    # Comando do browser pra "Abrir browser ao carregar" dos runners.
    # Vazio = usa QDesktopServices.openUrl (xdg-open no Linux). Pode ser
    # um caminho absoluto ("/usr/bin/firefox") ou nome no PATH ("chromium").
    browser_command: str = ""
    # Delay (ms) entre detectar a URL/ready_pattern e abrir o browser.
    # Why: alguns servers logam a URL antes de aceitar conexões — abrir na
    # hora bate em "ECONNREFUSED" no browser. Default 5000ms cobre cold
    # start de Glassfish/Spring Boot sem ficar perceptível em devservers
    # rápidos (Vite/Next). 0 = abre imediato.
    browser_open_delay_ms: int = 5000
    # Tamanhos persistidos dos splitters (largura/altura em px). [] = usar defaults.
    body_splitter_sizes: list[int] = field(default_factory=list)  # [sidebar, middle, right_dock] (legado pré-QtAds)
    body_dock_state: str = ""  # QtAds CDockManager.saveState() em base64
    # Schema version do body_dock_state. Bump aqui descarta states salvos
    # por versões anteriores (ex.: 0.52/0.53 salvaram layout com ordem de
    # criação errada que duplicava sidebar).
    body_dock_state_schema: int = 0
    right_splitter_sizes: list[int] = field(default_factory=list)  # [content, terminal]
    # Tamanhos persistidos do sub-splitter de baixo: [terminal_pane, runners_pane].
    bottom_sub_splitter_sizes: list[int] = field(default_factory=list)
    # Quais panes estavam minimizados na sessão anterior — restaurados no
    # startup pra reaparecer como chips na MinimizeTray + área colapsada.
    # Valores válidos: "workspace", "terminal_pane", "runners".
    minimized_panes: list[str] = field(default_factory=list)
    workspace_columns_sizes: list[int] = field(default_factory=list)  # legado, sem uso atual
    window_geometry: list[int] = field(default_factory=list)  # [x, y, w, h]
    # Dock direito (Tarefas + Git + Skills colapsáveis)
    right_dock_collapsed: dict = field(default_factory=dict)  # {panel_id: bool}
    # Estado colapsado dos workspaces na sidebar (persistente entre sessões).
    workspace_collapsed: dict = field(default_factory=dict)  # {workspace_id: bool}
    # Estado colapsado do submenu "Runners workspace" por workspace.
    runner_group_collapsed: dict = field(default_factory=dict)  # {workspace_id: bool}
    # Estado colapsado das seções do rodapé de runners da sidebar.
    runner_footer_collapsed: dict = field(default_factory=dict)  # {"workspace"|"console": bool}
    # Endpoint local pro plugin de browser (badge/faixa de worktree):
    # http://127.0.0.1:<porta>/state.json com o mapa porta → runner.
    browser_state_server_enabled: bool = True
    browser_state_server_port: int = 43210
    # Estado colapsado do bucket "Sessões Claude" por workspace.
    sessoes_collapsed: dict = field(default_factory=dict)  # {workspace_id: bool}
    # Estado colapsado das seções "FIXADOS" / "WORKSPACES" na sidebar.
    section_collapsed: dict = field(default_factory=dict)  # {"FIXADOS"|"WORKSPACES": bool}
    # Defaults pro LaunchClaudeDialog
    default_isolate_worktree: bool = False
    default_create_new_branch: bool = True
    branch_prefix: str = "claude"  # prefixo das branches sugeridas pro worktree
    # Apps auxiliares (PWAs embutidos): [{name, url, icon, slug}]
    apps: list[dict] = field(default_factory=list)
    # Notificações: re-aviso para tabs que ficaram aguardando sem ser focadas.
    # 0 desliga; valor mínimo prático é 15s (clamped no coordinator).
    notify_reminder_enabled: bool = True
    notify_reminder_seconds: int = 120
    # Liga notificações nativas do sistema (QSystemTrayIcon.showMessage).
    # Quando False, a inbox/badge ainda funcionam, mas sem toast.
    notify_native_enabled: bool = True
    # Textos das notificações. Configuráveis pra que cada notificação
    # identifique claramente o app + qual workspace concluiu — em vez de
    # banners genéricos tipo "Claude Code / Tarefa concluída".
    # `notify_app_name`: rótulo do app no banner (D-Bus app_name / tray tooltip
    #     / `notify-send -a`). Aparece como cabeçalho da notificação.
    # `notify_ready_prefix` / `notify_reminder_prefix`: prefixo do título nas
    #     notificações de "pronto" e "ainda aguardando" (formato: "<prefixo> —
    #     <workspace>"). Use string vazia pra esconder o prefixo.
    # `notify_hook_title_format`: template do título do hook Stop disparado
    #     pelo Claude Code via packaging/notify-hook.py. `{project}` é
    #     substituído pelo basename do cwd.
    # `notify_hook_default_body`: body do hook quando não dá pra ler a última
    #     mensagem do usuário do transcript.
    notify_app_name: str = "Claude Workspaces"
    notify_ready_prefix: str = "⏳ Aguardando"
    notify_decision_prefix: str = "❓ Decisão"
    notify_reminder_prefix: str = "🔁 Ainda aguardando"
    notify_hook_title_format: str = "Claude — {project}"
    notify_hook_default_body: str = "(turno encerrado)"
    # Som das notificações nativas. Usa a hint `sound-name` do
    # org.freedesktop.Notifications — o servidor (KDE Plasma, GNOME
    # Shell, dunst) toca o sample correspondente do tema sonoro via
    # libcanberra. Nomes padrão XDG: "message-new-instant", "message",
    # "complete", "bell", "alarm-clock-elapsed". Vazio = sem som.
    notify_sound_enabled: bool = True
    notify_sound_name: str = "message-new-instant"
    # Tempo de exibição (ms) do banner da notificação nativa.
    # -1 = usa o default do servidor (KDE/GNOME respeitam a config do SO);
    #  0 = sticky (banner não some sozinho — só fechando manualmente);
    # >0 = força esse tempo em ms, ignorando o default do SO.
    # Default 10000ms (10s) pra dar tempo de ler sem ficar sticky.
    notify_timeout_ms: int = 10000
    # Webhook do Discord — espelha as notificações da central num canal.
    # Quando `discord_webhook_enabled` é True e a URL está preenchida, cada
    # notificação emitida pelo NotificationService vira uma mensagem
    # (POST JSON) no webhook configurado, respeitando os mesmos mutes por
    # tipo/workspace da central. A URL tem o formato
    # https://discord.com/api/webhooks/<id>/<token>. Vazio = desligado.
    # Habilitado por padrão; só dispara de fato quando a URL está preenchida.
    discord_webhook_enabled: bool = True
    discord_webhook_url: str = ""
    # Debounce da transição working→idle no status da sidebar. Why: o parser
    # de status oscila entre is_working True/False enquanto o Claude alterna
    # tool calls e geração de texto dentro do mesmo turno. O app só mostra
    # "Ocioso" se ficar `idle_debounce_seconds` estável sem voltar a working
    # — evita flicker "Trabalhando ↔ Ocioso". Mínimo 0 (sem debounce),
    # máximo 120s.
    idle_debounce_seconds: int = 20
    # Mostra a barra de ações (Continuar / Ciclar modo / Effort / Modelo /
    # Encerrar) no topo de cada terminal. Toggle global controlado pelo
    # botão na top bar. Mesmo desligada, as ações continuam acessíveis
    # via menu de contexto na sidebar.
    show_terminal_actions: bool = True
    # Limite (USD) por janela de 5h do plano Anthropic — usado pra calcular
    # o % exibido na sidebar ("Plan usage limits" do claude.ai). Anthropic
    # não publica o número exato e o ratio drifta com o mix de mensagens
    # (input vs output têm pesos diferentes no quota interno). Default
    # $700 foi calibrado contra o ponto mais recente (claude.ai 8% com
    # nosso cost_usd em ~$56 → $700) num plano Max 5x. Ajustar via
    # settings.json se a UI divergir.
    plan_usd_limit_5h: float = 700.0
    # Limites semanais (USD) — replicam `Weekly limits` do claude.ai.
    # `all_models` = faixa "All models"; `sonnet` = faixa "Sonnet only".
    # Anthropic não publica em USD; defaults calibrados num ponto real
    # (claude.ai marcando 2% all-models com `cost_usd` semanal em $4730
    # → 100% ≈ $236k num plano Max 5x — número alto porque o quota
    # interno deles parece ter peso bem menor que custo-equivalente em
    # API pública). Ajustar via settings.json se necessário.
    plan_weekly_usd_limit_all: float = 236_000.0
    plan_weekly_usd_limit_sonnet: float = 118_000.0
    # Escopo de MCP por workspace: quando ligado, cada sessão claude sobe só
    # os servidores MCP do workspace (auto-inferidos pelo nome ou escolhidos na
    # edição do workspace), via --mcp-config --strict-mcp-config. Evita que
    # toda sessão carregue TODOS os MCP globais (grande economia de memória).
    # Desligado = comportamento antigo (Claude usa o global ~/.claude.json).
    mcp_scope_per_workspace: bool = True

    @classmethod
    def load(cls) -> "Settings":
        path = settings_file()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        valid = {f.name for f in fields(cls)}
        # Migração: se o usuário ainda está com o default antigo "✅ Pronto"
        # do notify_ready_prefix, troca pra "⏳ Aguardando" — alinha com o chip
        # da central de notificações e com a semântica real (agente aguardando
        # próxima instrução, não tarefa concluída).
        if data.get("notify_ready_prefix") == "✅ Pronto":
            data["notify_ready_prefix"] = "⏳ Aguardando"
        return cls(**{k: v for k, v in data.items() if k in valid})

    def save(self) -> None:
        path = settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def update_from(self, other: "Settings") -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))

    # ----- Backend dispatch -----

    def ai_command(self) -> str:
        """Retorna o comando do backend ativo (claude ou opencode)."""
        if self.ai_backend == "opencode":
            return self.opencode_command or "opencode"
        return self.claude_command or "claude"

    def ai_extra_args(self) -> list[str]:
        """Args extras configurados pelo usuário pro backend ativo."""
        if self.ai_backend == "opencode":
            return list(self.opencode_extra_args)
        return list(self.claude_extra_args)

    def claude_session_flags(self) -> list[str]:
        """Flags derivadas das configurações 'Claude' do app — anexadas ao
        argv junto com `claude_extra_args` em todo launch de sessão.
        Vazio quando o respectivo campo está vazio (não passa a flag)."""
        flags: list[str] = []
        if self.claude_permission_mode:
            flags += ["--permission-mode", self.claude_permission_mode]
        if self.claude_effort:
            flags += ["--effort", self.claude_effort]
        if self.claude_allowed_tools.strip():
            flags += ["--allowedTools", self.claude_allowed_tools.strip()]
        if self.claude_disallowed_tools.strip():
            flags += ["--disallowedTools", self.claude_disallowed_tools.strip()]
        return flags

    def opencode_session_flags(self) -> list[str]:
        """Flags derivadas das configurações opencode."""
        flags: list[str] = []
        if self.opencode_model:
            flags += ["-m", self.opencode_model]
        if self.opencode_agent:
            flags += ["--agent", self.opencode_agent]
        return flags

    def ai_session_flags(self) -> list[str]:
        """Flags de sessão pro backend ativo."""
        if self.ai_backend == "opencode":
            return self.opencode_session_flags()
        return self.claude_session_flags()

    def claude_launch_args(self) -> list[str]:
        """Args completos pra anexar após `claude_command`: extras configurados
        pelo usuário + flags derivadas das configurações 'Claude'."""
        return [*self.claude_extra_args, *self.claude_session_flags()]

    def ai_launch_args(self) -> list[str]:
        """Args completos pra anexar após `ai_command()` pro backend ativo."""
        return [*self.ai_extra_args(), *self.ai_session_flags()]

    def ide_command(self, ide_key: str) -> str:
        return {
            "intellij": self.intellij_command,
            "webstorm": self.webstorm_command,
            "pycharm": self.pycharm_command,
            "rider": self.rider_command,
            "vscode": self.vscode_command,
        }.get(ide_key, "")
