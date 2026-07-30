from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

from obase.exceptions import FSError

log = structlog.get_logger()

_DEFAULT_WORKING_DIR = Path.home() / ".obase" / "work"
_working_dir: Path | None = None


class FS:
    """Filesystem utilities for obase pipelines."""

    @classmethod
    def set_default_working_dir(cls, path: Path) -> None:
        """Override the default working directory."""
        global _working_dir
        _working_dir = path

    @classmethod
    def working_dir(cls) -> Path:
        """Return the active working directory, creating it if absent."""
        base = _working_dir if _working_dir is not None else _DEFAULT_WORKING_DIR
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create working dir {base}: {exc}") from exc
        return base

    @classmethod
    def run_dir(cls, run_id: str) -> Path:
        """Return (and create) a per-run subdirectory."""
        d = cls.working_dir() / run_id
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create run dir {d}: {exc}") from exc
        return d

    @classmethod
    def hash_file(cls, path: Path, algorithm: str = "sha256") -> str:
        """Return hex digest of a file's contents."""
        if not path.exists():
            raise FSError(f"File not found: {path}")
        h = hashlib.new(algorithm)
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def cleanup_old_runs(cls, max_age_seconds: float = 7 * 86400) -> list[Path]:
        """Remove run subdirectories older than *max_age_seconds*. Returns removed paths."""
        removed: list[Path] = []
        base = cls.working_dir()
        now = time.time()
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            age = now - entry.stat().st_mtime
            if age > max_age_seconds:
                try:
                    shutil.rmtree(entry)
                    removed.append(entry)
                    log.info("obase.fs.removed_old_run", path=str(entry), age_s=age)
                except OSError as exc:
                    log.warning("obase.fs.cleanup_error", path=str(entry), error=str(exc))
        return removed

    @classmethod
    def to_wsl_path(cls, windows_path: str) -> Path:
        """Convert a Windows path to its WSL /mnt/ equivalent."""
        if platform.system() != "Linux":
            raise FSError("WSL path conversion only supported on Linux/WSL")
        p = windows_path.replace("\\", "/")
        if len(p) >= 2 and p[1] == ":":
            drive = p[0].lower()
            rest = p[2:]
            return Path(f"/mnt/{drive}{rest}")
        raise FSError(f"Not a Windows path: {windows_path!r}")

    @classmethod
    def from_wsl_path(cls, wsl_path: Path | str) -> str:
        """Convert a WSL /mnt/<drive>/... path to Windows format."""
        p = str(wsl_path)
        if p.startswith("/mnt/") and len(p) > 6:
            drive = p[5].upper()
            rest = p[6:].replace("/", "\\")
            return f"{drive}:{rest}"
        raise FSError(f"Not a /mnt/ WSL path: {wsl_path!r}")

    @classmethod
    def reset_working_dir(cls) -> None:
        """Reset to default (used in tests)."""
        global _working_dir
        _working_dir = None

    @classmethod
    def ensure_dir(cls, path: Path) -> Path:
        """Create a directory (and parents) if it does not exist."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create directory {path}: {exc}") from exc
        return path

    @classmethod
    def safe_write(cls, path: Path, data: bytes | str) -> None:
        """Atomic-ish write via a temp file."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            if isinstance(data, str):
                tmp.write_text(data, encoding="utf-8")
            else:
                tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise FSError(f"Write failed for {path}: {exc}") from exc


@runtime_checkable
class FileStorage(Protocol):
    """S3/Local 上传下载抽象的统一接口(SPEC §1 ``obase.fs``)。"""

    async def upload(self, *, local_path: Path, key: str) -> str: ...

    async def download(self, *, key: str, local_path: Path) -> None: ...

    async def delete(self, *, key: str) -> bool: ...


class LocalFileStorage:
    """把 `key` 当作 `base_dir` 下的相对路径,纯本地磁盘实现,无外部依赖。"""

    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir

    def _resolve(self, key: str) -> Path:
        return self._base_dir / key

    async def upload(self, *, local_path: Path, key: str) -> str:
        if not local_path.exists():
            raise FSError(f"LocalFileStorage: local file not found: {local_path}")
        dest = self._resolve(key)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_path, dest)
        except OSError as exc:
            raise FSError(f"LocalFileStorage: upload failed for {key!r}: {exc}") from exc
        return key

    async def download(self, *, key: str, local_path: Path) -> None:
        src = self._resolve(key)
        if not src.exists():
            raise FSError(f"LocalFileStorage: key not found: {key!r}")
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, local_path)
        except OSError as exc:
            raise FSError(f"LocalFileStorage: download failed for {key!r}: {exc}") from exc

    async def delete(self, *, key: str) -> bool:
        target = self._resolve(key)
        if not target.exists():
            return False
        target.unlink()
        return True


class S3FileStorage:
    """S3(或兼容 S3 API 的服务,如 MinIO 传 endpoint_url)上传下载实现。

    boto3 走懒加载导入(``obase[storage]`` extra),不装这个 extra 时
    ``import obase.fs`` 本身不受影响,只有实际调用才会报错。
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region_name: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._region_name = region_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # noqa: PLC0415
            except ImportError as exc:
                raise FSError(
                    "S3FileStorage requires the 'boto3' package (obase[storage] extra)"
                ) from exc
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region_name,
            )
        return self._client

    async def upload(self, *, local_path: Path, key: str) -> str:
        if not local_path.exists():
            raise FSError(f"S3FileStorage: local file not found: {local_path}")
        client = self._get_client()
        try:
            await asyncio.to_thread(client.upload_file, str(local_path), self._bucket, key)
        except Exception as exc:
            raise FSError(f"S3FileStorage: upload failed for {key!r}: {exc}") from exc
        return key

    async def download(self, *, key: str, local_path: Path) -> None:
        client = self._get_client()
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(client.download_file, self._bucket, key, str(local_path))
        except Exception as exc:
            raise FSError(f"S3FileStorage: download failed for {key!r}: {exc}") from exc

    async def delete(self, *, key: str) -> bool:
        client = self._get_client()
        try:
            await asyncio.to_thread(client.delete_object, Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise FSError(f"S3FileStorage: delete failed for {key!r}: {exc}") from exc
        return True
