"""错误标签存储基础设施 (obase_error_tag_store)

职责：持久化学生的错误分类标签，支持诊断聚合。
"""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from typing import Any, List, Optional
from obase.persistence import PgPool, insert_one, query
from obase.uuid7 import uuid7

# 表名约定
SCHEMA = "public"
TABLE = "error_tags"

async def ensure_error_tag_table(pool: PgPool):
    """初始化错误标签表。"""
    from obase.persistence import ensure_table, ensure_index
    
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("student_id", "UUID NOT NULL"),
            ("question_id", "TEXT NOT NULL"),
            ("kc_id", "TEXT NOT NULL"),
            ("primary_tag", "TEXT NOT NULL"),
            ("secondary_tags", "TEXT[]"),
            ("reason", "TEXT"),
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
        ]
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        index_name="idx_error_tags_student_kc",
        columns="student_id, kc_id"
    )

async def store_error_tag(
    pool: PgPool,
    student_id: UUID,
    question_id: str,
    kc_id: str,
    primary_tag: str,
    secondary_tags: Optional[List[str]] = None,
    reason: Optional[str] = None
) -> UUID:
    """存储一条错误标签记录。"""
    record_id = uuid7()
    await insert_one(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        row={
            "id": record_id,
            "student_id": student_id,
            "question_id": question_id,
            "kc_id": kc_id,
            "primary_tag": primary_tag,
            "secondary_tags": secondary_tags or [],
            "reason": reason,
            "created_at": datetime.now(timezone.utc)
        }
    )
    return record_id

async def get_error_distribution(
    pool: PgPool,
    student_id: UUID,
    kc_id: Optional[str] = None
) -> List[dict]:
    """获取错误类型分布。"""
    where = "student_id = $1"
    params = [student_id]
    if kc_id:
        where += " AND kc_id = $2"
        params.append(kc_id)
        
    sql = f"""
        SELECT primary_tag, COUNT(*) as count
        FROM "{SCHEMA}"."{TABLE}"
        WHERE {where}
        GROUP BY primary_tag
    """
    return await query(pool=pool, sql=sql, params=params)

__version__ = "0.1.0"
