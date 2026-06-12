"""obase.docker.images — Image pull/list/delete and system prune."""

from __future__ import annotations

import time
from typing import Any

import docker  # type: ignore[import-untyped]
import docker.errors  # type: ignore[import-untyped]

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError, ObaseAuthError
from obase.docker.client import ImagePullResult, PruneResult, _make_client


def docker_image_pull(
    *,
    image: str,
    tag: str = "latest",
    docker_host: str = "unix:///var/run/docker.sock",
    auth_config: dict[str, Any] | None = None,
) -> ImagePullResult:
    """拉取 docker 镜像."""
    client = _make_client(docker_host)
    ref = f"{image}:{tag}"

    already_local = False
    try:
        client.images.get(ref)
        already_local = True
    except docker.errors.ImageNotFound:
        pass
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error checking local image: {exc}") from exc

    t0 = time.monotonic()
    try:
        img = client.images.pull(image, tag=tag, auth_config=auth_config)
    except docker.errors.ImageNotFound as exc:
        raise OBaseNotFoundError(f"Image not found: {ref}") from exc
    except docker.errors.APIError as exc:
        msg = str(exc)
        if "unauthorized" in msg.lower() or "authentication" in msg.lower() or "403" in msg:
            raise ObaseAuthError(f"Authentication failed for {ref}: {exc}") from exc
        raise OBaseConnectionError(f"Failed to pull image {ref}: {exc}") from exc
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to pull image {ref}: {exc}") from exc
    elapsed = int((time.monotonic() - t0) * 1000)

    return ImagePullResult(
        image=image,
        tag=tag,
        digest=img.id or "",
        pulled=not already_local,
        size_bytes=img.attrs.get("Size", 0),
        elapsed_ms=elapsed,
    )


def docker_image_list(
    *,
    docker_host: str = "unix:///var/run/docker.sock",
) -> list[dict[str, Any]]:
    """列出 docker 镜像."""
    client = _make_client(docker_host)
    try:
        images = client.images.list()
        return [
            {
                "id": img.id,
                "tags": img.tags,
                "size_bytes": img.attrs.get("Size", 0),
                "created_at": img.attrs.get("Created", ""),
            }
            for img in images
        ]
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error listing images: {exc}") from exc


def docker_image_delete(
    *,
    image: str,
    force: bool = False,
    docker_host: str = "unix:///var/run/docker.sock",
) -> dict[str, Any]:
    """删除 docker 镜像."""
    client = _make_client(docker_host)
    try:
        res = client.images.remove(image, force=force)
        return {"result": res}
    except docker.errors.ImageNotFound as exc:
        raise OBaseNotFoundError(f"Image not found: {image}") from exc
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error deleting image: {exc}") from exc


def docker_system_prune(
    *,
    volumes: bool = False,
    docker_host: str = "unix:///var/run/docker.sock",
) -> PruneResult:
    """清理停止的容器、悬空镜像、未使用网络."""
    client = _make_client(docker_host)
    try:
        c_result = client.containers.prune()
        i_result = client.images.prune(filters={"dangling": True})
        v_removed = 0
        if volumes:
            v_result = client.volumes.prune()
            v_removed = len(v_result.get("VolumesDeleted") or [])

        containers_removed = len(c_result.get("ContainersDeleted") or [])
        images_removed = len(i_result.get("ImagesDeleted") or [])
        space = (c_result.get("SpaceReclaimed", 0) or 0) + (i_result.get("SpaceReclaimed", 0) or 0)

        return PruneResult(
            containers_removed=containers_removed,
            images_removed=images_removed,
            volumes_removed=v_removed,
            space_reclaimed_bytes=space,
        )
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker prune failed: {exc}") from exc


__all__ = [
    "docker_image_pull",
    "docker_image_list",
    "docker_image_delete",
    "docker_system_prune",
]
