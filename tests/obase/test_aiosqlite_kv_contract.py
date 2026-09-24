"""obase owns aiosqlite: public import loads SQLiteKVStore / MemoryBank."""

from __future__ import annotations

from pathlib import Path

import pytest

from obase import IKV_Store, MemoryBank, MemoryItem, SQLiteKVStore, cosine_similarity
from obase.contracts import IKV_Store as IKV_StoreDirect


def test_public_exports_available() -> None:
    for name in ("IKV_Store", "SQLiteKVStore", "MemoryBank", "MemoryItem", "cosine_similarity"):
        assert name in __import__("obase").__all__
    assert IKV_Store is IKV_StoreDirect


def test_aiosqlite_declared_in_pyproject() -> None:
    text = Path(__file__).resolve().parents[2].joinpath("pyproject.toml").read_text()
    assert "aiosqlite" in text


def test_contracts_are_abstract() -> None:
    with pytest.raises(TypeError):
        IKV_Store()  # type: ignore[abstract]


async def test_sqlite_kv_roundtrip(tmp_path: Path) -> None:
    store = SQLiteKVStore(str(tmp_path / "kv.db"))
    await store.put("session/alpha", {"state": 1})
    assert await store.get("session/alpha") == {"state": 1}
    assert await store.get("missing") is None
    listed = await store.list_prefix("session/")
    assert listed == [{"state": 1}]


def test_memory_item_and_cosine() -> None:
    item = MemoryItem(
        memory_id="m1",
        context_description="ctx",
        failed_attempt={"what": "a"},
        successful_strategy={"what": "b"},
        context_vector=[1.0, 0.0],
    )
    assert item.to_dict()["memory_id"] == "m1"
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([], []) == 0.0
