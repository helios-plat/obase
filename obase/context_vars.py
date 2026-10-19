"""3O 范式全栈 — 通用 ContextVar 封装 (零业务逻辑).

子 Task 自动继承父 Context; set 返回 token, reset 恢复。
cost_tracker 的 current_cost 即本模式的特例。
"""

from __future__ import annotations

from contextvars import ContextVar, Token


class ContextSlot[T]:
    """泛型 ContextVar 槽位: set / get / reset 的薄封装。"""

    def __init__(self, name: str, default: T):
        self.name = name
        self._var: ContextVar[T] = ContextVar(name, default=default)

    def set(self, value: T) -> Token[T]:
        return self._var.set(value)

    def get(self) -> T:
        return self._var.get()

    def reset(self, token: Token[T]) -> None:
        self._var.reset(token)
