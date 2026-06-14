"""
SMS 验证码基础设施 (Dev Mock)
=============================
obase/sms.py
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

async def send_otp(phone: str) -> str:
    """发送短信验证码。开发环境下固定返回 123456。"""
    # 模拟网络延迟
    code = "123456"
    logger.info(f"Dev Mock SMS: Sent OTP {code} to {phone}")
    print(f"DEBUG: Sent OTP {code} to {phone}")
    return code

async def verify_otp(phone: str, code: str) -> bool:
    """校验验证码。开发环境下固定校验 123456。"""
    # TODO: 接入 Redis 进行真实校验
    return code == "123456"
