"""Erros específicos do subsistema de plugins.

Convenção: `ValidationError` carrega `errors: list[str]` para que a UI
possa exibir todos os problemas de uma vez (ao invés de uma falha por vez)."""

from __future__ import annotations

from ..errors import WorkspacesError


class PluginError(WorkspacesError):
    """Base — qualquer falha relacionada a plugin herda daqui."""


class ManifestError(PluginError):
    """plugin.yaml ausente, ilegível ou com YAML inválido."""


class ValidationError(PluginError):
    """Manifesto/bundle violou uma ou mais regras da spec.

    `errors` é a lista de mensagens (uma por violação). A mensagem do
    Exception é o resumo (`N erros`)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} erro(s) na validação do plugin")

    def __str__(self) -> str:  # pragma: no cover - trivial
        lines = [f"{len(self.errors)} erro(s):"]
        lines.extend(f"  - {e}" for e in self.errors)
        return "\n".join(lines)


class RegistryError(PluginError):
    """Falha ao instalar, desinstalar ou listar plugins."""


class PermissionDeniedError(PluginError):
    """Handler tentou usar capacidade sem permissão declarada."""


class StorageQuotaError(PluginError):
    """Storage do plugin excedeu 10 MB (seção 5.5)."""
