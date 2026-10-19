"""obase.dlt_pipeline_store — 基于声明式 Schema 自动推导的数据清洗与持久化管道。

职责:
- 根据输入记录自动推导 Schema（列名、类型）
- 支持表级别的增量合并与行计数
- 为 oprim.dlt_schema_normalize / oskill.auto_data_curation 提供基础设施

例:
    >>> store = DltPipelineStore("my_dataset")
    >>> store.auto_infer_and_load("users", [{"name": "Alice", "age": 30}])
    {'status': 'success', 'table': 'users', 'rows_inserted': 1}
"""

from __future__ import annotations

from typing import Any

__all__ = ["DltPipelineStore", "DltPipelineStoreError"]


class DltPipelineStoreError(RuntimeError):
    """DLT 管道存储错误."""


class DltPipelineStore:
    """基于声明式 Schema 自动推导的数据清洗与持久化管道.

    设计:
    - 生产环境可注入 dlt (data load tool) 或 DuckDB 实现替换
    - 接口层提供内存存储参考实现
    """

    def __init__(self, dataset_name: str = "veya_research") -> None:
        self.dataset_name = dataset_name
        self._schemas: dict[str, list[str]] = {}
        self._tables: dict[str, list[dict[str, Any]]] = {}
        self._row_counts: dict[str, int] = {}

    def auto_infer_and_load(
        self, table_name: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """自动根据 Dict 数据推导 Schema 并合并存储.

        Args:
            table_name: 目标表名
            records: 记录列表

        Returns:
            {
                "status": "success" | "empty",
                "table": str,
                "schema": list[str],
                "rows_inserted": int,
            }
        """
        if not records:
            return {"status": "empty", "table": table_name, "rows_inserted": 0}

        # 自动推导 Schema（第一个记录的 keys）
        inferred_columns = list(records[0].keys())
        self._schemas[table_name] = inferred_columns

        # 合并存储
        if table_name not in self._tables:
            self._tables[table_name] = []
        self._tables[table_name].extend(records)
        self._row_counts[table_name] = len(self._tables[table_name])

        return {
            "status": "success",
            "table": table_name,
            "schema": inferred_columns,
            "rows_inserted": len(records),
        }

    def get_table(self, table_name: str) -> list[dict[str, Any]]:
        """获取表中所有记录.

        Args:
            table_name: 表名

        Returns:
            记录列表
        """
        return list(self._tables.get(table_name, []))

    def get_schema(self, table_name: str) -> list[str]:
        """获取表的 Schema.

        Args:
            table_name: 表名

        Returns:
            列名列表
        """
        return list(self._schemas.get(table_name, []))

    def row_count(self, table_name: str) -> int:
        """获取表的行数."""
        return self._row_counts.get(table_name, 0)

    def list_tables(self) -> list[str]:
        """列出所有表名."""
        return sorted(self._tables.keys())

    def truncate_table(self, table_name: str) -> None:
        """清空表."""
        self._tables.pop(table_name, None)
        self._schemas.pop(table_name, None)
        self._row_counts.pop(table_name, None)

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "dataset_name": self.dataset_name,
            "table_count": len(self._tables),
            "total_rows": sum(self._row_counts.values()),
            "tables": self.list_tables(),
        }
