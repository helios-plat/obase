"""obase.docker.client — Docker client helpers, models, and parse utilities."""

from __future__ import annotations

import time
from typing import Any, Literal

import docker  # type: ignore[import-untyped]
import docker.errors  # type: ignore[import-untyped]
from pydantic import BaseModel

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ContainerInfo(BaseModel):
    container_id: str
    name: str
    image: str
    state: Literal["running", "exited", "paused", "restarting", "dead", "created"]
    status: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    health: Literal["healthy", "unhealthy", "starting", "none"] | None
    restart_count: int
    labels: dict[str, str]
    ports: list[dict[str, Any]]
    mounts: list[dict[str, Any]]


class ContainerOpResult(BaseModel):
    container_id: str
    operation: Literal["start", "stop", "restart"]
    success: bool
    elapsed_ms: int
    state_before: str
    state_after: str


class LogLine(BaseModel):
    timestamp: str
    stream: Literal["stdout", "stderr"]
    message: str


class ImagePullResult(BaseModel):
    image: str
    tag: str
    digest: str
    pulled: bool
    size_bytes: int
    elapsed_ms: int


class ContainerStats(BaseModel):
    container_id: str
    cpu_percent: float
    memory_usage_bytes: int
    memory_limit_bytes: int
    memory_percent: float
    network_rx_bytes: int
    network_tx_bytes: int
    block_read_bytes: int
    block_write_bytes: int
    pids: int
    timestamp: str


class ContainerCreateResult(BaseModel):
    container_id: str
    name: str
    warnings: list[str]


class PruneResult(BaseModel):
    containers_removed: int
    images_removed: int
    volumes_removed: int
    space_reclaimed_bytes: int


class NodeInfo(BaseModel):
    docker_host: str
    reachable: bool
    server_version: str | None
    os: str | None
    arch: str | None
    cpus: int | None
    memory_bytes: int | None
    containers_running: int | None
    error: str | None


class ContainerRenameResult(BaseModel):
    container_id: str
    old_name: str
    new_name: str


class NetworkCreateResult(BaseModel):
    network_id: str
    name: str
    driver: str


class NetworkDeleteResult(BaseModel):
    network_id: str
    name: str
    deleted: bool


class VolumeCreateResult(BaseModel):
    name: str
    driver: str
    mountpoint: str
    created_at: str


class ContainerExecResult(BaseModel):
    container_id: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(docker_host: str) -> docker.DockerClient:
    try:
        return docker.DockerClient(base_url=docker_host)
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(
            f"Cannot connect to docker daemon at {docker_host}: {exc}"
        ) from exc


def _get_container(client: docker.DockerClient, container_id: str) -> Any:
    try:
        return client.containers.get(container_id)
    except docker.errors.NotFound as exc:
        raise OBaseNotFoundError(f"Container not found: {container_id}") from exc
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error while fetching container: {exc}") from exc


def _parse_state(
    attrs: dict[str, Any],
) -> Literal["running", "exited", "paused", "restarting", "dead", "created"]:
    raw = attrs.get("State", {}).get("Status", "").lower()
    valid = {"running", "exited", "paused", "restarting", "dead", "created"}
    return raw if raw in valid else "exited"  # type: ignore[return-value]


def _parse_health(
    attrs: dict[str, Any],
) -> Literal["healthy", "unhealthy", "starting", "none"] | None:
    health = attrs.get("State", {}).get("Health")
    if health is None:
        return None
    status = health.get("Status", "none").lower()
    valid = {"healthy", "unhealthy", "starting", "none"}
    return status if status in valid else "none"  # type: ignore[return-value]


def _parse_ports(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    ports = []
    bindings = attrs.get("HostConfig", {}).get("PortBindings") or {}
    for container_port, host_bindings in bindings.items():
        proto = "tcp"
        cp = container_port
        if "/" in container_port:
            cp, proto = container_port.split("/", 1)
        for hb in host_bindings or []:
            ports.append(
                {
                    "host_port": hb.get("HostPort"),
                    "container_port": cp,
                    "protocol": proto,
                }
            )
    return ports


def _parse_mounts(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": m.get("Type"),
            "source": m.get("Source"),
            "destination": m.get("Destination"),
            "mode": m.get("Mode"),
            "rw": m.get("RW"),
        }
        for m in attrs.get("Mounts", [])
    ]


__all__ = [
    "_make_client",
    "_get_container",
    "_parse_state",
    "_parse_health",
    "_parse_ports",
    "_parse_mounts",
    "ContainerInfo",
    "ContainerOpResult",
    "LogLine",
    "ImagePullResult",
    "ContainerStats",
    "ContainerCreateResult",
    "PruneResult",
    "NodeInfo",
    "ContainerRenameResult",
    "NetworkCreateResult",
    "NetworkDeleteResult",
    "VolumeCreateResult",
    "ContainerExecResult",
]

# Re-export time so submodules don't re-import
_time = time
