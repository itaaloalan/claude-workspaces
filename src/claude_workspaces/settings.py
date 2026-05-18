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
    # Tamanhos persistidos dos splitters (largura/altura em px). [] = usar defaults.
    body_splitter_sizes: list[int] = field(default_factory=list)  # [sidebar, middle, right_dock]
    right_splitter_sizes: list[int] = field(default_factory=list)  # [content, terminal]
    workspace_columns_sizes: list[int] = field(default_factory=list)  # legado, sem uso atual
    window_geometry: list[int] = field(default_factory=list)  # [x, y, w, h]
    # Dock direito (Tarefas + Git + Skills colapsáveis)
    right_dock_collapsed: dict = field(default_factory=dict)  # {panel_id: bool}
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
    # Debounce da transição working→idle no status da sidebar. Why: o parser
    # de status oscila entre is_working True/False enquanto o Claude alterna
    # tool calls e geração de texto dentro do mesmo turno. O app só mostra
    # "Ocioso" se ficar `idle_debounce_seconds` estável sem voltar a working
    # — evita flicker "Trabalhando ↔ Ocioso". Mínimo 0 (sem debounce),
    # máximo 120s.
    idle_debounce_seconds: int = 20

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
