import os.path
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Task:
    id: str = field(default_factory=_new_id)
    title: str = ""
    done: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=str(data.get("id") or _new_id()),
            title=str(data.get("title") or ""),
            done=bool(data.get("done", False)),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass
class Workspace:
    name: str
    folders: list[str] = field(default_factory=list)
    description: str = ""
    id: str = field(default_factory=_new_id)
    tasks: list[Task] = field(default_factory=list)

    @property
    def primary_folder(self) -> str | None:
        return self.folders[0] if self.folders else None

    @property
    def extra_folders(self) -> list[str]:
        return self.folders[1:] if len(self.folders) > 1 else []

    def launch_paths(self) -> tuple[str, list[str]]:
        """Decide o cwd e as pastas extras pra --add-dir.

        Se todas as pastas são irmãs sob um mesmo pai (ex: map-web e
        map-api dentro de map/), usa o pai como cwd sem nenhum --add-dir
        — assim o Claude vê tudo como um único projeto unificado.

        Caso contrário (pastas não relacionadas), volta pro esquema
        original: primeira pasta como cwd, demais via --add-dir.
        """
        if not self.folders:
            raise ValueError("Workspace sem pastas")
        if len(self.folders) == 1:
            return self.folders[0], []

        try:
            common = os.path.commonpath(self.folders)
        except ValueError:
            return self.folders[0], self.folders[1:]

        common_path = Path(common)
        if all(Path(f).parent == common_path for f in self.folders):
            return common, []

        return self.folders[0], self.folders[1:]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        return cls(
            name=data["name"],
            folders=list(data.get("folders", [])),
            description=data.get("description", ""),
            id=str(data.get("id") or _new_id()),
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
        )
