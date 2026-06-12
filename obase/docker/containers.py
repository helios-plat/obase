"""obase.docker.containers — Container lifecycle and runtime operations."""

from __future__ import annotations

import time
from typing import Any, Literal

import docker  # type: ignore[import-untyped]
import docker.errors  # type: ignore[import-untyped]

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError, OBaseValidationError
from obase.docker.client import (
    ContainerCreateResult,
    ContainerExecResult,
    ContainerInfo,
    ContainerOpResult,
    ContainerRenameResult,
    ContainerStats,
    LogLine,
    _get_container,
    _make_client,
    _parse_health,
    _parse_mounts,
    _parse_ports,
    _parse_state,
)


def docker_container_inspect(
    *,
    container_id: str,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerInfo:
    """查容器完整状态信息."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)
    container.reload()
    attrs = container.attrs

    state_attrs = attrs.get("State", {})
    started = state_attrs.get("StartedAt") or None
    finished = state_attrs.get("FinishedAt") or None
    if started and started.startswith("0001"):
        started = None
    if finished and finished.startswith("0001"):
        finished = None

    return ContainerInfo(
        container_id=attrs["Id"],
        name=attrs.get("Name", "").lstrip("/"),
        image=attrs.get("Config", {}).get("Image", ""),
        state=_parse_state(attrs),
        status=container.status,
        started_at=started,
        finished_at=finished,
        exit_code=state_attrs.get("ExitCode"),
        health=_parse_health(attrs),
        restart_count=attrs.get("RestartCount", 0),
        labels=attrs.get("Config", {}).get("Labels") or {},
        ports=_parse_ports(attrs),
        mounts=_parse_mounts(attrs),
    )


def docker_container_logs(
    *,
    container_id: str,
    lines: int = 100,
    since: str | None = None,
    until: str | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> list[LogLine]:
    """读容器日志."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    kwargs: dict[str, Any] = {"timestamps": True, "stream": False}
    if since is not None:
        kwargs["since"] = since
    if until is not None:
        kwargs["until"] = until
    if since is None:
        kwargs["tail"] = lines

    try:
        raw: bytes = container.logs(**kwargs)
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to retrieve logs: {exc}") from exc

    result: list[LogLine] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            ts, msg = parts
        else:
            ts, msg = "", line
        result.append(LogLine(timestamp=ts, stream="stdout", message=msg))
    return result


def docker_container_start(
    *,
    container_id: str,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerOpResult:
    """启动容器."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    state_before = container.status
    t0 = time.monotonic()
    try:
        container.start()
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to start container: {exc}") from exc
    elapsed = int((time.monotonic() - t0) * 1000)
    container.reload()

    return ContainerOpResult(
        container_id=container.id,
        operation="start",
        success=True,
        elapsed_ms=elapsed,
        state_before=state_before,
        state_after=container.status,
    )


def docker_container_stop(
    *,
    container_id: str,
    timeout_sec: int = 10,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerOpResult:
    """停止容器."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    state_before = container.status
    t0 = time.monotonic()
    try:
        container.stop(timeout=timeout_sec)
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to stop container: {exc}") from exc
    elapsed = int((time.monotonic() - t0) * 1000)
    container.reload()

    return ContainerOpResult(
        container_id=container.id,
        operation="stop",
        success=True,
        elapsed_ms=elapsed,
        state_before=state_before,
        state_after=container.status,
    )


def docker_container_restart(
    *,
    container_id: str,
    timeout_sec: int = 10,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerOpResult:
    """重启容器."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    state_before = container.status
    t0 = time.monotonic()
    try:
        container.restart(timeout=timeout_sec)
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to restart container: {exc}") from exc
    elapsed = int((time.monotonic() - t0) * 1000)
    container.reload()

    return ContainerOpResult(
        container_id=container.id,
        operation="restart",
        success=True,
        elapsed_ms=elapsed,
        state_before=state_before,
        state_after=container.status,
    )


def docker_container_stats(
    *,
    container_id: str,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerStats:
    """读容器资源使用快照."""
    from datetime import UTC, datetime

    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    try:
        raw = container.stats(stream=False)
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Failed to get container stats: {exc}") from exc

    cpu_delta = raw.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - raw.get(
        "precpu_stats", {}
    ).get("cpu_usage", {}).get("total_usage", 0)
    system_delta = raw.get("cpu_stats", {}).get("system_cpu_usage", 0) - raw.get(
        "precpu_stats", {}
    ).get("system_cpu_usage", 0)
    percpu = raw.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage") or [0]
    num_cpus = len(percpu)
    cpu_percent = (cpu_delta / system_delta * num_cpus * 100.0) if system_delta > 0 else 0.0

    mem = raw.get("memory_stats", {})
    mem_usage = mem.get("usage", 0)
    mem_limit = mem.get("limit", 0)
    mem_percent = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0

    net_rx = net_tx = 0
    for iface in raw.get("networks", {}).values():
        net_rx += iface.get("rx_bytes", 0)
        net_tx += iface.get("tx_bytes", 0)

    blk_read = blk_write = 0
    for bio in raw.get("blkio_stats", {}).get("io_service_bytes_recursive") or []:
        op = bio.get("op", "").lower()
        if op == "read":
            blk_read += bio.get("value", 0)
        elif op == "write":
            blk_write += bio.get("value", 0)

    return ContainerStats(
        container_id=container_id,
        cpu_percent=round(cpu_percent, 2),
        memory_usage_bytes=mem_usage,
        memory_limit_bytes=mem_limit,
        memory_percent=round(mem_percent, 2),
        network_rx_bytes=net_rx,
        network_tx_bytes=net_tx,
        block_read_bytes=blk_read,
        block_write_bytes=blk_write,
        pids=raw.get("pids_stats", {}).get("current", 0),
        timestamp=datetime.now(UTC).isoformat(),
    )


def docker_container_list(
    *,
    all: bool = False,  # noqa: A002
    filters: dict[str, Any] | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> list[ContainerInfo]:
    """列出 docker 容器."""
    client = _make_client(docker_host)
    try:
        containers = client.containers.list(all=all, filters=filters)
        return [
            ContainerInfo(
                container_id=c.id,
                name=c.name,
                image=c.image.tags[0] if c.image.tags else c.image.id,
                state=_parse_state(c.attrs),
                status=c.status,
                started_at=c.attrs.get("State", {}).get("StartedAt"),
                finished_at=c.attrs.get("State", {}).get("FinishedAt"),
                exit_code=c.attrs.get("State", {}).get("ExitCode"),
                health=_parse_health(c.attrs),
                restart_count=c.attrs.get("RestartCount", 0),
                labels=c.attrs.get("Config", {}).get("Labels") or {},
                ports=_parse_ports(c.attrs),
                mounts=_parse_mounts(c.attrs),
            )
            for c in containers
        ]
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error listing containers: {exc}") from exc


def docker_container_create(
    *,
    image: str,
    name: str,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
    ports: dict[str, int | list[int] | None] | None = None,
    volumes: dict[str, dict[str, str]] | None = None,
    labels: dict[str, str] | None = None,
    restart_policy: Literal["no", "always", "on-failure", "unless-stopped"] = "unless-stopped",
    network: str | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerCreateResult:
    """创建容器 (不启动)."""
    client = _make_client(docker_host)
    kwargs: dict[str, Any] = {
        "image": image,
        "name": name,
        "detach": True,
        "restart_policy": {"Name": restart_policy},
    }
    if command:
        kwargs["command"] = command
    if env:
        kwargs["environment"] = env
    if ports:
        kwargs["ports"] = ports
    if volumes:
        kwargs["volumes"] = volumes
    if labels:
        kwargs["labels"] = labels
    if network:
        kwargs["network"] = network

    try:
        container = client.containers.create(**kwargs)
        return ContainerCreateResult(
            container_id=container.id,
            name=container.name,
            warnings=container.attrs.get("Warnings") or [],
        )
    except docker.errors.ImageNotFound as exc:
        raise OBaseNotFoundError(f"Image not found: {image}") from exc
    except docker.errors.APIError as exc:
        msg = str(exc)
        if "port is already allocated" in msg or "bind" in msg.lower():
            raise OBaseValidationError(
                f"Container create failed (port conflict?): {msg[:300]}"
            ) from exc
        raise OBaseConnectionError(f"Docker API error: {msg[:300]}") from exc


def docker_container_rename(
    *,
    container_id: str,
    new_name: str,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerRenameResult:
    """重命名容器."""
    client = _make_client(docker_host)
    container = _get_container(client, container_id)
    old_name = container.name.lstrip("/")

    try:
        container.rename(new_name)
        return ContainerRenameResult(
            container_id=container.id,
            old_name=old_name,
            new_name=new_name,
        )
    except docker.errors.APIError as exc:
        msg = str(exc)
        if "Conflict" in msg or "already in use" in msg.lower():
            raise OBaseValidationError(f"Rename failed (conflict): {msg[:300]}") from exc
        raise OBaseConnectionError(f"Docker API error renaming container: {msg[:300]}") from exc
    except docker.errors.DockerException as exc:
        raise OBaseConnectionError(f"Docker error renaming container: {exc}") from exc


def docker_container_exec(
    *,
    container_id: str,
    command: list[str],
    workdir: str | None = None,
    env: dict[str, str] | None = None,
    user: str | None = None,
    timeout_sec: int = 30,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerExecResult:
    """在容器内执行命令."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    client = _make_client(docker_host)
    container = _get_container(client, container_id)

    t0 = time.perf_counter()

    def _do_exec() -> tuple[int, tuple[bytes | None, bytes | None]]:
        return container.exec_run(
            cmd=command,
            workdir=workdir,
            environment=env,
            user=user,
            demux=True,
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_exec)
            exit_code, (stdout_bytes, stderr_bytes) = future.result(timeout=timeout_sec)

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        elapsed = int((time.perf_counter() - t0) * 1000)

        return ContainerExecResult(
            container_id=container.id,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=elapsed,
        )
    except FutureTimeoutError as exc:
        raise OBaseConnectionError(f"Exec timeout ({timeout_sec}s): {command}") from exc
    except docker.errors.APIError as exc:
        raise OBaseConnectionError(f"Docker API error executing command: {exc}") from exc
    except Exception as exc:
        raise OBaseConnectionError(f"Unexpected error executing command: {exc}") from exc


__all__ = [
    "docker_container_inspect",
    "docker_container_logs",
    "docker_container_start",
    "docker_container_stop",
    "docker_container_restart",
    "docker_container_stats",
    "docker_container_list",
    "docker_container_create",
    "docker_container_rename",
    "docker_container_exec",
]
