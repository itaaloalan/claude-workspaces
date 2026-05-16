"""Cobertura mínima do PluginConfigStore.

Foco nos comportamentos não-óbvios: chaves removidas do manifesto não
vazam pro effective; reset volta pro default; arquivo JSON sobrevive a
restart (instância nova lê o mesmo arquivo)."""

from __future__ import annotations

import json

from claude_workspaces.plugins.config_store import PluginConfigStore


def test_defaults_quando_arquivo_nao_existe(tmp_path):
    store = PluginConfigStore(tmp_path, {"a": 1, "b": "x"})
    assert store.effective() == {"a": 1, "b": "x"}
    assert not store.is_overridden("a")


def test_set_persiste_e_segunda_instancia_le(tmp_path):
    PluginConfigStore(tmp_path, {"a": 1}).set("a", 42)
    other = PluginConfigStore(tmp_path, {"a": 1})
    assert other.get("a") == 42
    assert other.is_overridden("a")


def test_reset_volta_pro_default(tmp_path):
    s = PluginConfigStore(tmp_path, {"a": 1})
    s.set("a", 42)
    s.reset("a")
    assert s.get("a") == 1
    assert not s.is_overridden("a")


def test_chaves_removidas_do_manifesto_nao_vazam(tmp_path):
    # Usuário gravou config, depois autor removeu o campo do manifesto:
    # leitura efetiva ignora a chave órfã, mas o arquivo preserva (downgrade
    # não destrói o valor).
    PluginConfigStore(tmp_path, {"a": 1, "b": 2}).set("a", 10)
    PluginConfigStore(tmp_path, {"a": 1, "b": 2}).set("b", 20)
    sem_b = PluginConfigStore(tmp_path, {"a": 1})
    assert "b" not in sem_b.effective()
    assert sem_b.get("a") == 10
    # Arquivo ainda tem a chave órfã
    saved = json.loads((tmp_path / ".state" / "config.json").read_text())
    assert saved.get("b") == 20


def test_arquivo_corrompido_cai_pra_default(tmp_path):
    state = tmp_path / ".state"
    state.mkdir()
    (state / "config.json").write_text("isso não é JSON {")
    s = PluginConfigStore(tmp_path, {"a": 7})
    assert s.get("a") == 7


def test_set_rejeita_chave_vazia(tmp_path):
    s = PluginConfigStore(tmp_path, {})
    import pytest
    with pytest.raises(ValueError):
        s.set("", "x")
