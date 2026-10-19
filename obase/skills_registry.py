"""obase.skills_registry — 动态 Skills / Rules 规则管理与注册表（支持上下文扩展名匹配）。

职责:
- 根据文件扩展名、域名关键词匹配适用的编码规则
- 支持运行时动态注册/移除规则
- 为 oskill.skills_dynamic_inject 提供规则匹配基础设施

例:
    >>> reg = SkillsRegistry()
    >>> reg.match_rules("main.py")
    ['Follow PEP8. Use explicit type hints...']
    >>> reg.match_rules("program.rs")
    ['Follow idiomatic Rust...']
"""

from __future__ import annotations

from typing import Any

__all__ = ["SkillsRegistry", "SkillsRegistryError"]


class SkillsRegistryError(RuntimeError):
    """Skills 注册表错误."""


# 内置默认规则集
_DEFAULT_RULES: dict[str, str] = {
    ".py": "Follow PEP8. Use explicit type hints. Prefer dataclasses for DTOs.",
    ".ts": "Strict TypeScript. No 'any' type. Use interfaces for domain models.",
    ".tsx": "React best practices. Use functional components. Memoize callbacks.",
    ".js": "Use ES modules. Prefer const over let. Avoid var.",
    ".rs": "Follow idiomatic Rust. Ensure memory safety, explicit error handling via Result.",
    ".go": "Follow effective Go. Handle errors explicitly. Use interfaces sparingly.",
    ".java": "Follow Google Java Style. Prefer composition over inheritance.",
    ".sql": "Use parameterized queries. Avoid SELECT *. Add proper indexes.",
    ".yaml": "Use 2-space indentation. Quote strings with special characters.",
    ".toml": "Follow TOML spec. Use dotted keys for nested tables.",
    ".json": "Validate against schema. No trailing commas. Use camelCase keys.",
    ".md": "Use semantic line breaks. Follow CommonMark spec.",
    ".sh": "Use shellcheck directives. Prefer [[ over [. Quote all variables.",
    ".dockerfile": "Multi-stage builds. Minimize layers. Use specific base image tags.",
    "solana": (
        "Ensure account ownership check, reentrancy guards, "
        "and arithmetic overflow protection."
    ),
    "ethereum": (
        "Check effects-interactions pattern. Use SafeMath or Solidity ^0.8. "
        "Avoid tx.origin for auth."
    ),
    "security": (
        "Validate all inputs. Apply principle of least privilege. "
        "No hardcoded secrets. Use parameterized queries."
    ),
}


class SkillsRegistry:
    """动态 Skills / Rules 规则管理与注册表.

    支持：
    - 文件扩展名精确匹配 (.py, .rs)
    - 关键词子串匹配 (solana, security)
    - 运行时动态增删规则
    """

    def __init__(self) -> None:
        self._rules: dict[str, str] = dict(_DEFAULT_RULES)

    def match_rules(self, context_key: str) -> list[str]:
        """根据上下文文件扩展名或关键词匹配生效 Rules.

        Args:
            context_key: 文件名、路径或领域关键词

        Returns:
            匹配到的规则文本列表
        """
        if not context_key:
            return []
        matched: list[str] = []
        context_lower = context_key.lower()
        for key, rule in self._rules.items():
            key_lower = key.lower()
            # 精确扩展名匹配
            if key_lower.startswith(".") and context_lower.endswith(key_lower):
                matched.append(rule)
            # 关键词子串匹配
            elif not key_lower.startswith(".") and key_lower in context_lower:
                matched.append(rule)
        return matched

    def register_rule(self, key: str, rule: str) -> None:
        """注册或覆盖一条规则.

        Args:
            key: 匹配键（如 ".py" 或 "solana"）
            rule: 规则文本

        Raises:
            SkillsRegistryError: key 或 rule 为空
        """
        if not key or not rule:
            raise SkillsRegistryError("key and rule must be non-empty")
        self._rules[key] = rule

    def remove_rule(self, key: str) -> bool:
        """移除一条规则.

        Returns:
            True 如果规则存在并被移除
        """
        if key in self._rules:
            del self._rules[key]
            return True
        return False

    def list_rules(self) -> dict[str, str]:
        """列出所有已注册的规则（返回副本）."""
        return dict(self._rules)

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "rules_count": len(self._rules),
            "extension_rules": sum(1 for k in self._rules if k.startswith(".")),
            "domain_rules": sum(1 for k in self._rules if not k.startswith(".")),
        }
