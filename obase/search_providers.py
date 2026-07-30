"""obase.search_providers — 内置 obase.SearchProvider 实现。

LogSearchProvider：不接真实搜索引擎,只把索引状态记进内存字典——真实商户
对接见 MeiliSearch/Algolia 等外部 SDK,不在本模块。用于没有真实搜索服务
凭据的环境里跑集成测试。
"""

from __future__ import annotations

from typing import Any


class LogSearchProvider:
    """把 upsert/delete 操作记进内存字典,不真的对外发送。"""

    def __init__(self) -> None:
        self.indexed: dict[str, dict[str, Any]] = {}

    async def upsert_doc(self, *, index: str, document: dict[str, Any]) -> bool:
        self.indexed.setdefault(index, {})[document["id"]] = document
        return True

    async def delete_doc(self, *, index: str, doc_id: str) -> bool:
        removed = self.indexed.get(index, {}).pop(doc_id, None)
        return removed is not None
