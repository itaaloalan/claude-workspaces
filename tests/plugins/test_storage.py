import threading

import pytest

from claude_workspaces.plugins import storage as plugin_storage
from claude_workspaces.plugins.errors import StorageQuotaError


@pytest.fixture
def store(tmp_path):
    return plugin_storage.PluginStorage(tmp_path / "plug")


def test_get_missing_key_returns_none(store):
    assert store.get("foo") is None


def test_set_then_get(store):
    store.set("foo", {"a": 1})
    assert store.get("foo") == {"a": 1}


def test_set_persists_across_instances(tmp_path):
    install_dir = tmp_path / "plug"
    s1 = plugin_storage.PluginStorage(install_dir)
    s1.set("k", "v")
    s2 = plugin_storage.PluginStorage(install_dir)
    assert s2.get("k") == "v"


def test_set_empty_key_raises(store):
    with pytest.raises(ValueError):
        store.set("", 1)


def test_set_non_string_key_raises(store):
    with pytest.raises(ValueError):
        store.set(123, "x")  # type: ignore[arg-type]


def test_delete_removes_key(store):
    store.set("a", 1)
    store.set("b", 2)
    store.delete("a")
    assert store.get("a") is None
    assert store.get("b") == 2


def test_delete_missing_key_is_noop(store):
    store.delete("nope")  # não levanta
    assert store.get("nope") is None


def test_clear_removes_file(store, tmp_path):
    store.set("a", 1)
    assert (tmp_path / "plug" / ".state" / "store.json").exists()
    store.clear()
    assert not (tmp_path / "plug" / ".state" / "store.json").exists()
    assert store.get("a") is None


def test_clear_when_empty_is_noop(store):
    store.clear()  # não levanta nem cria nada
    assert store.size_bytes() == 0


def test_size_bytes_zero_when_no_file(store):
    assert store.size_bytes() == 0


def test_size_bytes_grows_with_data(store):
    store.set("k", "v")
    s1 = store.size_bytes()
    assert s1 > 0
    store.set("k2", "x" * 1000)
    assert store.size_bytes() > s1


def test_quota_exceeded_raises(store):
    blob = "x" * (11 * 1024 * 1024)
    with pytest.raises(StorageQuotaError):
        store.set("big", blob)


def test_quota_keeps_old_data(store):
    """Se write falhar por quota, dados anteriores devem permanecer intactos."""
    store.set("ok", "valor-bom")
    with pytest.raises(StorageQuotaError):
        store.set("big", "x" * (11 * 1024 * 1024))
    assert store.get("ok") == "valor-bom"
    assert store.get("big") is None


def test_corrupted_json_treated_as_empty(tmp_path):
    install_dir = tmp_path / "plug"
    (install_dir / ".state").mkdir(parents=True)
    (install_dir / ".state" / "store.json").write_text("{not json")
    s = plugin_storage.PluginStorage(install_dir)
    assert s.get("any") is None
    # E permite escrita por cima
    s.set("k", "v")
    assert s.get("k") == "v"


def test_non_dict_json_treated_as_empty(tmp_path):
    install_dir = tmp_path / "plug"
    (install_dir / ".state").mkdir(parents=True)
    (install_dir / ".state" / "store.json").write_text("[1,2,3]")
    s = plugin_storage.PluginStorage(install_dir)
    assert s.get("any") is None


def test_lock_is_reentrant(store):
    """RLock permite re-entrada na mesma thread (set chama _load+_write
    enquanto segura o lock)."""
    # Se não fosse reentrante isso travaria — basta verificar que termina.
    store.set("a", 1)
    store.set("b", 2)
    assert store.get("a") == 1
    assert store.get("b") == 2


def test_lock_shared_per_install_dir(tmp_path):
    """Duas instâncias apontando pro mesmo install_dir compartilham lock —
    evita corrida entre handlers concorrentes do mesmo plugin."""
    install_dir = tmp_path / "plug"
    s1 = plugin_storage.PluginStorage(install_dir)
    s2 = plugin_storage.PluginStorage(install_dir)
    assert s1._lock is s2._lock


def test_concurrent_writes_dont_lose_data(tmp_path):
    """Stress: várias threads escrevendo chaves distintas — todas devem
    persistir."""
    install_dir = tmp_path / "plug"
    s = plugin_storage.PluginStorage(install_dir)

    def writer(start: int):
        for i in range(start, start + 20):
            s.set(f"k{i}", i)

    threads = [threading.Thread(target=writer, args=(i * 20,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Reabre e confere
    s2 = plugin_storage.PluginStorage(install_dir)
    for i in range(80):
        assert s2.get(f"k{i}") == i


def test_unicode_value_roundtrip(store):
    store.set("k", {"texto": "olá, café — não fui só"})
    assert store.get("k") == {"texto": "olá, café — não fui só"}
