"""
对象存储基础设施 (MinIO)
========================
obase/oss.py
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional
from minio import Minio
from obase.config import settings

logger = logging.getLogger(__name__)

# 全局客户端单例
_client: Optional[Minio] = None

def get_oss_client() -> Minio:
    """获取或初始化 Minio 客户端。"""
    global _client
    if _client is None:
        # endpoint 需要处理 localhost -> minio (如果是 docker 内部)
        # 这里先信任 settings 中的配置
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False # 开发环境通常不用 SSL
        )
        
        # 确保 Bucket 存在
        if not _client.bucket_exists(settings.MINIO_BUCKET):
            _client.make_bucket(settings.MINIO_BUCKET)
            logger.info(f"Created bucket: {settings.MINIO_BUCKET}")
            
    return _client

async def upload_file(
    local_path: Path, 
    object_name: str, 
    content_type: str = "application/octet-stream"
) -> str:
    """上传本地文件到 OSS。返回 object_name。"""
    client = get_oss_client()
    client.fput_object(
        settings.MINIO_BUCKET,
        object_name,
        str(local_path),
        content_type=content_type
    )
    return object_name

async def get_download_url(object_name: str, expires_seconds: int = 3600) -> str:
    """获取文件的预签名下载链接。"""
    client = get_oss_client()
    return client.presigned_get_object(
        settings.MINIO_BUCKET,
        object_name,
        expires=expires_seconds
    )
