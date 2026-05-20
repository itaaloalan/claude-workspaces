import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    return Path.home() / ".config" / "claude-workspaces"


def settings_file() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Settings:
    claude_command: str = "claude"
    claude_extra_args: list[str] = field(default_factory=list)
    terminal_command: str = "konsole"
    shell_command: str = ""  # "" = autodetect from /etc/passwd (login shell)
    vscode_command: str = "code"
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
    body_splitter_sizes: list[int] = field(default_factory=list)  # [sidebar, middle, right_dock]
    right_splitter_sizes: list[int] = field(default_factory=list)  # [content, terminal]
    workspace_columns_sizes: list[int] = field(default_factory=list)  # legado, sem uso atual
    window_geometry: list[int] = field(default_factory=list)  # [x, y, w, h]
    # Dock direito (Tarefas + Git + Skills colapsáveis)
    right_dock_collapsed: dict = field(default_factory=dict)  # {panel_id: bool}
    # Estado colapsado dos workspaces na sidebar (persistente entre sessões).
    workspace_collapsed: dict = field(default_factory=dict)  # {workspace_id: bool}
    # Estado colapsado do submenu "Runners workspace" por workspace.
    runner_group_collapsed: dict = field(default_factory=dict)  # {workspace_id: bool}
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
    notify_ready_prefix: str = "✅ Pronto"
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

    def ide_command(self, ide_key: str) -> str:
        return {
            "intellij": self.intellij_command,
            "webstorm": self.webstorm_command,
            "pycharm": self.pycharm_command,
            "rider": self.rider_command,
            "vscode": self.vscode_command,
        }.get(ide_key, "")
