"""认知状态数据类型 + 初始状态工厂（obase 拥有）。

3O 约束：obase 是基础设施，**不得反向依赖 3O（oprim/oskill/omodul）**。
"状态长什么样"（KCState）与"初始状态怎么建"（new_state_from_prior / fsrs_new_card）
属数据 / 基础设施层，归 obase；而"状态怎么更新"的算法（bkt_update / fsrs_review 等）
留在 oprim。oprim 反过来从这里 import 这些类型（oprim→obase 合法、单向）。

此前 obase/cognitive_store.py 直接 `from oprim ... import`，违反 obase→3O 反向依赖红线；
把类型上移到 obase 后，依赖方向恢复为 oprim→obase。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class KCState:
    """贝叶斯知识追踪状态（知识组件级）。

    kc_id: 知识组件标识符
    p_init: 初始掌握概率先验
    p_transit: 一次练习后从未掌握→掌握的转移概率
    p_guess: 未掌握状态下答对的概率（猜对）
    p_slip: 已掌握状态下答错的概率（失误）
    p_mastery: 当前掌握概率 P(L)，None 表示使用先验
    long_term_mastery: 去遗忘平滑的长期掌握度
    last_interaction_ts: 上次交互 unix 时间戳
    n_attempts: 累计交互次数
    """
    kc_id: str
    p_init: float = 0.20
    p_transit: float = 0.20
    p_guess: float = 0.15
    p_slip: float = 0.12
    p_mastery: Optional[float] = None
    p_recognition: Optional[float] = None       # 识别维度掌握概率（M-G）
    p_recognition_init: float = 0.20             # 识别维度先验
    long_term_mastery: Optional[float] = None
    last_interaction_ts: Optional[float] = None
    n_attempts: int = 0

    def current(self) -> float:
        return self.p_mastery if self.p_mastery is not None else self.p_init


def new_state_from_prior(*, kc_id: str, prior: dict) -> KCState:
    """从先验参数字典创建初始 KCState。"""
    return KCState(
        kc_id=kc_id,
        p_init=prior.get("p_init", 0.2),
        p_transit=prior.get("p_transit", 0.2),
        p_guess=prior.get("p_guess", 0.15),
        p_slip=prior.get("p_slip", 0.12),
    )


def fsrs_new_card() -> dict:
    """创建新 FSRS 记忆卡片（初始状态）。"""
    from fsrs import Card
    return Card().to_dict()
