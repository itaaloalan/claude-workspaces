import subprocess

from .models import Workspace


class LauncherError(Exception):
    pass


def launch_claude(workspace: Workspace) -> None:
    if not workspace.primary_folder:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")

    claude_cmd = ["claude"]
    for extra in workspace.extra_folders:
        claude_cmd += ["--add-dir", extra]

    konsole_cmd = [
        "konsole",
        "--workdir", workspace.primary_folder,
        "-e", *claude_cmd,
    ]
    subprocess.Popen(konsole_cmd)


def launch_konsole(workspace: Workspace) -> None:
    if not workspace.primary_folder:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    subprocess.Popen(["konsole", "--workdir", workspace.primary_folder])


def launch_vscode(workspace: Workspace) -> None:
    if not workspace.folders:
        raise LauncherError(f"Workspace '{workspace.name}' não tem nenhuma pasta")
    subprocess.Popen(["code", *workspace.folders])
