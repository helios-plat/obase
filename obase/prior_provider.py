"""
BKT 先验参数提供者（带缓存）
===========================
obase/prior_provider.py
"""

from typing import Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.models import BKTPrior

class PriorProvider:
    """提供 BKT 先验参数，支持内存缓存。"""
    
    _cache: Dict[str, dict] = {}
    _is_warmed: bool = False

    @classmethod
    async def warm_up(cls, session: AsyncSession):
        """预热缓存，加载所有先验参数。"""
        stmt = select(BKTPrior)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        
        cls._cache = {
            f"{r.knowledge_point}:{r.question_type}": {
                "p_init": r.p_init,
                "p_transit": r.p_transit,
                "p_guess": r.p_guess,
                "p_slip": r.p_slip
            }
            for r in rows
        }
        cls._is_warmed = True

    @classmethod
    async def get_prior(
        cls, 
        session: Optional[AsyncSession], 
        kc_id: str, 
        question_type: str = "solve"
    ) -> dict:
        """获取指定 KC 和题型的先验参数。"""
        if not cls._is_warmed and session is not None:
            await cls.warm_up(session)
            
        key = f"{kc_id}:{question_type}"
        if key in cls._cache:
            return cls._cache[key]
            
        # 兜底逻辑 1: 如果找不到对应题型，尝试寻找该 KC 的任意一个题型
        for k, v in cls._cache.items():
            if k.startswith(f"{kc_id}:"):
                return v
        
        # 兜底逻辑 2: 终极默认值 (与 guangdong_math_kc 保持一致)
        return {"p_init": 0.20, "p_transit": 0.20, "p_guess": 0.15, "p_slip": 0.12}

    @classmethod
    def clear_cache(cls):
        cls._cache = {}
        cls._is_warmed = False
