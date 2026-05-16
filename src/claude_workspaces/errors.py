"""Hierarquia simples de erros do app + helpers padronizados.

Convenção:
- Erros operacionais (subprocess, IO, git) → uma das subclasses abaixo
- Erros de programação (TypeError, AttributeError, etc.) ficam como Python
- UI captura as subclasses e mostra mensagem amigável; coordinators
  loggam com `log.exception` antes de propagar/converter
"""

from __future__ import annotations


class WorkspacesError(Exception):
    """Base — toda exceção custom do app herda daqui."""


class LaunchError(WorkspacesError):
    """Falha ao iniciar Claude / shell / IDE / etc."""


class GitError(WorkspacesError):
    """Comando git falhou (worktree, checkout, commit, etc.)."""


class PtyError(WorkspacesError):
    """Falha no fork/exec do pty ou no IO subsequente."""


class StorageError(WorkspacesError):
    """Leitura/escrita de workspaces.json, settings.json, etc."""


class McpError(WorkspacesError):
    """Operações sobre ~/.claude.json (MCP postgres) falharam."""
