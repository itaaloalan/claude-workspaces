import uuid
from dataclasses import asdict, dataclass, field


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


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
        return cls(
            name=data["name"],
            folders=list(data.get("folders", [])),
            description=data.get("description", ""),
            id=str(data.get("id") or _new_id()),
            branch_prefix=str(data.get("branch_prefix") or ""),
            default_isolate_worktree=isolate,
            default_create_new_branch=create_branch,
        )
