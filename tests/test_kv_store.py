from __future__ import annotations

import pytest

from obase import KVStoreProvider, SQLiteKVStore


@pytest.mark.asyncio
async def test_sqlite_kv_store_durable_upsert_and_delete(tmp_path):
    path = tmp_path / "kv.db"
    store = SQLiteKVStore(path)
    assert isinstance(store, KVStoreProvider)
    assert await store.get("missing") is None
    await store.put("state/1", {"nested": {"n": 1}, "unicode": "状态"})
    assert await store.get("state/1") == {"nested": {"n": 1}, "unicode": "状态"}
    await store.put("state/1", {"n": 2})
    assert await store.count() == 1
    await store.close()

    reopened = SQLiteKVStore(path)
    assert await reopened.get("state/1") == {"n": 2}
    assert await reopened.delete("state/1") is True
    assert await reopened.delete("state/1") is False
    assert await reopened.count() == 0
    await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_kv_store_validates_input(tmp_path):
    store = SQLiteKVStore(tmp_path / "valid.db")
    with pytest.raises(ValueError, match="non-empty"):
        await store.put("  ", {"x": 1})
    with pytest.raises(TypeError, match="dictionary"):
        await store.put("x", [1, 2])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Out of range float values"):
        await store.put("x", {"n": float("nan")})
    await store.close()
