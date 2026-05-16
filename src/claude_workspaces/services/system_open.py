"""Helpers pra abrir paths/URLs no sistema (xdg-open, editor configurado).

Centraliza a chamada `subprocess.Popen(["xdg-open", path])` pra que a UI
chame `open_in_file_manager(path)` em vez de hardcodar. Mais fácil de
mockar em testes e de trocar a implementação por workspace/SO depois.
"""

import logging
import subprocess

from ..errors import LaunchError

log = logging.getLogger(__name__)


def open_in_file_manager(path: str) -> None:
    """Abre o path no gerenciador de arquivos do sistema. Levanta
    LaunchError se xdg-open não estiver disponível."""
    try:
        subprocess.Popen(["xdg-open", path])
    except FileNotFoundError as e:
        raise LaunchError(
            "xdg-open não está instalado (pacote xdg-utils)"
        ) from e


def open_in_editor(path: str, editor_command: str = "code") -> None:
    """Abre o path no editor configurado. Levanta LaunchError se o
    comando não existir."""
    try:
        subprocess.Popen([editor_command, path])
    except FileNotFoundError as e:
        raise LaunchError(
            f"editor '{editor_command}' não encontrado no PATH"
        ) from e
