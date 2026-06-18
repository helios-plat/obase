"""互动历史存储基础设施 (obase_interaction_history)

职责：持久化苏格拉底引导会话，供家长回看及元认知审计。
"""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from typing import Any, List, Optional
import json
from obase.persistence import PgPool, insert_one, query
from obase.uuid7 import uuid7

SCHEMA = "public"
TABLE = "interaction_history"

async def ensure_interaction_history_table(pool: PgPool):
    """初始化互动历史表。"""
    from obase.persistence import ensure_table, ensure_index
    
    await ensure_table(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        columns=[
            ("id", "UUID PRIMARY KEY"),
            ("student_id", "UUID NOT NULL"),
            ("question_id", "TEXT"),
            ("input_type", "TEXT NOT NULL"), # 'image', 'text', 'voice'
            ("initial_input", "TEXT"),
            ("metacog_eval", "JSONB"),       # 元认知自评数据
            ("decision_trail", "JSONB"),     # 引导决策链 (omodul 4支柱之一)
            ("final_output", "TEXT"),
            ("cost", "NUMERIC(12, 4)"),      # 消耗金额 (omodul 4支柱之一)
            ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("completed_at", "TIMESTAMPTZ"),
            ("retention_days", "INTEGER NOT NULL DEFAULT 365"),
            ("is_minor", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ]
    )
    await ensure_index(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        index_name="idx_interaction_student_time",
        columns="student_id, created_at DESC"
    )

async def start_interaction_session(
    pool: PgPool,
    student_id: UUID,
    input_type: str,
    initial_input: str,
    question_id: Optional[str] = None
) -> UUID:
    """开启一个新的互动会话。"""
    session_id = uuid7()
    await insert_one(
        pool=pool,
        schema=SCHEMA,
        table=TABLE,
        row={
            "id": session_id,
            "student_id": student_id,
            "question_id": question_id,
            "input_type": input_type,
            "initial_input": initial_input,
            "created_at": datetime.now(timezone.utc)
        }
    )
    return session_id

async def update_interaction_session(
    pool: PgPool,
    session_id: UUID,
    metacog_eval: Optional[dict] = None,
    decision_trail: Optional[List[dict]] = None,
    final_output: Optional[str] = None,
    cost: Optional[float] = None,
    is_completed: bool = False
) -> None:
    """更新会话状态。"""
    from obase.persistence import update_one
    
    updates = {}
    if metacog_eval is not None:
        updates["metacog_eval"] = json.dumps(metacog_eval)
    if decision_trail is not None:
        updates["decision_trail"] = json.dumps(decision_trail)
    if final_output is not None:
        updates["final_output"] = final_output
    if cost is not None:
        updates["cost"] = cost
    if is_completed:
        updates["completed_at"] = datetime.now(timezone.utc)
        
    if updates:
        await update_one(
            pool=pool,
            schema=SCHEMA,
            table=TABLE,
            where={"id": session_id},
            row=updates
        )

async def get_student_history(
    pool: PgPool,
    student_id: UUID,
    limit: int = 20,
    offset: int = 0
) -> List[dict]:
    """获取学生的历史互动记录。"""
    sql = f"""
        SELECT * FROM "{SCHEMA}"."{TABLE}"
        WHERE student_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
    """
    return await query(pool=pool, sql=sql, params=[student_id, limit, offset])

__version__ = "0.1.0"


async def purge_expired_interactions(
    pool: PgPool,
    *,
    dry_run: bool = False,
) -> int:
    """删除超过 retention_days 的互动历史记录。

    未成年人数据默认保留 365 天，由服务层定期调用此函数清理。

    Args:
        pool: 数据库连接池。
        dry_run: True 时只返回待删除数量，不实际删除。

    Returns:
        实际删除（或待删除）的记录数。

    Example:
        >>> count = await purge_expired_interactions(pool)
        >>> print(f"Deleted {count} expired records")
    """
    from obase.persistence import query, execute
    count_sql = f"""
        SELECT COUNT(*) FROM {SCHEMA}.{TABLE}
        WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL
    """
    rows = await query(pool=pool, sql=count_sql)
    count = rows[0]["count"] if rows else 0
    if dry_run:
        return count
    delete_sql = f"""
        DELETE FROM {SCHEMA}.{TABLE}
        WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL
    """
    await execute(pool=pool, sql=delete_sql)
    return count
