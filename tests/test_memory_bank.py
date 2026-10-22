from __future__ import annotations

import pytest

from obase import MemoryBank, MemoryItem


@pytest.mark.asyncio
async def test_memory_bank_persists_searches_updates_and_deletes(tmp_path):
    path = tmp_path / "memories.db"
    bank = MemoryBank(path)
    item = MemoryItem(
        memory_id="MEM-9",
        context_description="cache stampede fix",
        failed_attempt={"action": "direct query", "reason": "thundering herd"},
        successful_strategy={"action": "single-flight", "reason": "dedupe concurrent"},
        context_vector=[0.25, 0.75],
    )
    await bank.add(item)
    assert await bank.count() == 1
    bank.close()

    reopened = MemoryBank(path)
    hits = await reopened.search_experience("cache stampede concurrent", top_k=3)
    assert hits[0].memory_id == "MEM-9"
    assert hits[0].context_vector == [0.25, 0.75]
    assert (await reopened.list_all())[0].successful_strategy["action"] == "single-flight"

    await reopened.add(
        MemoryItem(
            memory_id="MEM-9",
            context_description="cache stampede mitigation updated",
            failed_attempt={"reason": "thundering herd"},
            successful_strategy={"action": "single-flight"},
        )
    )
    assert await reopened.count() == 1
    assert (await reopened.list_all())[0].context_description.endswith("updated")
    assert await reopened.delete("MEM-9") is True
    assert await reopened.delete("MEM-9") is False
    assert await reopened.count() == 0
    reopened.close()


def test_memory_item_rejects_invalid_data():
    with pytest.raises(ValueError, match="memory_id"):
        MemoryItem(memory_id=" ", context_description="valid context")
    with pytest.raises(ValueError, match="finite numbers"):
        MemoryItem(
            memory_id="MEM-10",
            context_description="valid context",
            context_vector=[float("nan")],
        )
