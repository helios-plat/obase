"""3O 范式 Phase 4 — omodul 业务事务基类配置 (obase 横切基础设施提供).

规范 §5.3: 所有 omodul 的 Config 类必须继承自本基类,
并显式覆写 _enabled_pillars (至少包含一项支柱)。
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel


class OmodulBaseConfig(BaseModel):
    """omodul 业务事务配置基类。

    子类必须声明:
      - _omodul_name / _omodul_version: 事务标识
      - _enabled_pillars: 启用支柱 (fingerprint / decision_trail / cost ...)
      - _fingerprint_fields: 指纹字段 (禁止包含 PII)
    """

    _omodul_name: ClassVar[str] = ""
    _omodul_version: ClassVar[str] = ""
    _enabled_pillars: ClassVar[set[str]] = set()
    _fingerprint_fields: ClassVar[set[str]] = set()
