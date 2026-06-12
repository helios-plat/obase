"""obase.docker.networks — Network operations and node info."""

from __future__ import annotations

from typing import Any, Literal

import docker  # type: ignore[import-untyped]
import docker.errors  # type: ignore[import-untyped]

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError, OBaseValidationError
from obase.docker.client import NetworkCreateResult, NetworkDeleteResult, NodeInfo, _make_client


def docker_network_list(
    *,
    docker_host: str = "unix:///var/run/docker.sock",
) -> list[dict[str, Any]]:
    """列出 docker 网络."""
    client = _make_client(docker_host)
    try:
        networks = client.networks.list()
        return [
            {
                "id": net.id,
                "name": net.name,
                "driver": net.attrs.get("Driver", ""),
                "scope": net.attrs.get("Scope", ""),
                "internal": net.attrs.get("Internal", False),
            }
            for net in networks
        ]
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error listing networks: {exc}") from exc


def docker_network_create(
    *,
    name: str,
    driver: Literal["bridge", "host", "overlay", "macvlan", "none"] = "bridge",
    internal: bool = False,
    labels: dict[str, str] | None = None,
    options: dict[str, str] | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> NetworkCreateResult:
    """创建 docker 网络."""
    client = _make_client(docker_host)
    try:
        net = client.networks.create(
            name=name, driver=driver, internal=internal, labels=labels, options=options
        )
        return NetworkCreateResult(
            network_id=net.id,
            name=net.name,
            driver=net.attrs.get("Driver", ""),
        )
    except docker.errors.APIError as exc:
        if "already exists" in str(exc).lower():
            raise OBaseValidationError(f"Network already exists: {name}") from exc
        raise OBaseConnectionError(f"Docker API error creating network: {exc}") from exc


def docker_network_delete(
    *,
    network_id: str,
    docker_host: str = "unix:///var/run/docker.sock",
) -> NetworkDeleteResult:
    """删除 docker 网络."""
    client = _make_client(docker_host)
    try:
        net = client.networks.get(network_id)
        name = net.name
        net.remove()
        return NetworkDeleteResult(
            network_id=network_id,
            name=name,
            deleted=True,
        )
    except docker.errors.NotFound as exc:
        raise OBaseNotFoundError(f"Network not found: {network_id}") from exc
    except docker.errors.APIError as exc:
        if "active endpoints" in str(exc).lower():
            raise OBaseValidationError(f"Network {network_id} has active endpoints") from exc
        raise OBaseConnectionError(f"Docker API error deleting network: {exc}") from exc


def docker_node_info(
    *,
    docker_host: str,
    timeout_sec: int = 5,
) -> NodeInfo:
    """探测远程 Docker 节点基本信息. 永不 raise 网络错误 (返 reachable=False)."""
    import docker as docker_lib

    try:
        client = docker_lib.DockerClient(base_url=docker_host, timeout=timeout_sec)
        info = client.info()
        return NodeInfo(
            docker_host=docker_host,
            reachable=True,
            server_version=client.version().get("Version"),
            os=info.get("OperatingSystem"),
            arch=info.get("Architecture"),
            cpus=info.get("NCPU"),
            memory_bytes=info.get("MemTotal"),
            containers_running=info.get("ContainersRunning"),
            error=None,
        )
    except Exception as exc:
        return NodeInfo(
            docker_host=docker_host,
            reachable=False,
            server_version=None,
            os=None,
            arch=None,
            cpus=None,
            memory_bytes=None,
            containers_running=None,
            error=str(exc)[:200],
        )


__all__ = [
    "docker_network_list",
    "docker_network_create",
    "docker_network_delete",
    "docker_node_info",
]
