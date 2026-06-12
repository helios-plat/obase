"""obase.docker.volumes — Volume create/list/delete operations."""

from __future__ import annotations

from typing import Any

import docker  # type: ignore[import-untyped]
import docker.errors  # type: ignore[import-untyped]

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError, OBaseValidationError
from obase.docker.client import VolumeCreateResult, _make_client


def docker_volume_list(
    *,
    docker_host: str = "unix:///var/run/docker.sock",
) -> list[dict[str, Any]]:
    """列出 docker 数据卷."""
    client = _make_client(docker_host)
    try:
        volumes = client.volumes.list()
        return [
            {
                "name": vol.name,
                "driver": vol.attrs.get("Driver", ""),
                "mountpoint": vol.attrs.get("Mountpoint", ""),
                "created_at": vol.attrs.get("CreatedAt", ""),
                "labels": vol.attrs.get("Labels") or {},
            }
            for vol in volumes
        ]
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error listing volumes: {exc}") from exc


def docker_volume_delete(
    *,
    name: str,
    force: bool = False,
    docker_host: str = "unix:///var/run/docker.sock",
) -> dict[str, Any]:
    """删除 docker 数据卷."""
    client = _make_client(docker_host)
    try:
        vol = client.volumes.get(name)
        vol.remove(force=force)
        return {"deleted": name}
    except docker.errors.NotFound as exc:
        raise OBaseNotFoundError(f"Volume not found: {name}") from exc
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error deleting volume: {exc}") from exc


def docker_volume_create(
    *,
    name: str,
    driver: str = "local",
    labels: dict[str, str] | None = None,
    driver_opts: dict[str, str] | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> VolumeCreateResult:
    """创建 docker 数据卷."""
    client = _make_client(docker_host)
    try:
        vol = client.volumes.create(
            name=name, driver=driver, labels=labels, driver_opts=driver_opts
        )
        return VolumeCreateResult(
            name=vol.name,
            driver=vol.attrs.get("Driver", ""),
            mountpoint=vol.attrs.get("Mountpoint", ""),
            created_at=vol.attrs.get("CreatedAt", ""),
        )
    except docker.errors.APIError as exc:
        if "already exists" in str(exc).lower():
            raise OBaseValidationError(f"Volume already exists: {name}") from exc
        raise OBaseConnectionError(f"Docker API error creating volume: {exc}") from exc


__all__ = [
    "docker_volume_list",
    "docker_volume_delete",
    "docker_volume_create",
]
