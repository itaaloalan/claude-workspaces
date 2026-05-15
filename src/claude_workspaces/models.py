import os.path
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Workspace:
    name: str
    folders: list[str] = field(default_factory=list)
    description: str = ""

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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        return cls(
            name=data["name"],
            folders=list(data.get("folders", [])),
            description=data.get("description", ""),
        )
