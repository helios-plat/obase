"""3O 范式全栈 — obase 基础类型 (定义类型, 无业务逻辑)."""

from __future__ import annotations

from typing import Any

# JSON 可序列化值域 (KV 存储 / 总线载荷 / 结果字典的通用约束)
type JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]
# 标准结果字典形态 (原子操作 / 业务事务统一返回)
type ResultDict = dict[str, Any]
# 标准错误形态
type ErrorDict = dict[str, Any]
