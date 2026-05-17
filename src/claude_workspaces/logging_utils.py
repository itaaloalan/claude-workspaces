"""Decorators e helpers pra padronizar tratamento de exceção.

A regra do app é: erro inesperado loga com `log.exception(...)` com
contexto e — quando seguro — não propaga. Bare except sem log é
proibido (audita-se em CI).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def log_exceptions(
    *,
    message: str | None = None,
    default: Any = None,
    reraise: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator que captura qualquer Exception e loga com stack-trace.

    Use em handlers de signal/slot do Qt, callbacks de QTimer e outros
    sítios onde uma exception não tratada quebraria o event loop ou
    ficaria invisível.

    Args:
        message: prefixo do log. Default = "Exceção em <func.__qualname__>".
        default: valor retornado quando a função lança. Default None.
        reraise: re-levanta depois de logar (útil pra propagar erro
            esperado pra um handler externo).

    Exemplo:

        @log_exceptions(message="Falha ao carregar plugin", default=False)
        def load_plugin(path: str) -> bool:
            ...
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        logger = logging.getLogger(fn.__module__)
        msg = message or f"Exceção em {fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception:
                logger.exception(msg)
                if reraise:
                    raise
                return default

        return wrapper

    return decorator
