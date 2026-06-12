"""obase.docker.compose — Docker Compose operations via CLI."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Literal

from obase.exceptions import OBaseConnectionError, OBaseNotFoundError


def compose_up(
    *,
    compose_file: str,
    project_name: str | None = None,
    detach: bool = True,
    pull: Literal["always", "missing", "never"] = "missing",
    docker_host: str = "unix:///var/run/docker.sock",
) -> dict[str, Any]:
    """docker-compose up."""
    if not os.path.exists(compose_file):
        raise OBaseNotFoundError(f"Compose file not found: {compose_file}")

    cmd = ["docker", "compose", "-f", compose_file]
    if project_name:
        cmd.extend(["-p", project_name])
    cmd.extend(["up", "--pull", pull])
    if detach:
        cmd.append("-d")

    env = os.environ.copy()
    env["DOCKER_HOST"] = docker_host

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        started_services: list[str] = []
        for line in proc.stderr.splitlines():
            if "Started" in line or "Created" in line:
                parts = line.split()
                if len(parts) >= 2:
                    started_services.append(parts[1])
        return {
            "started_services": sorted(set(started_services)),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.CalledProcessError as exc:
        raise OBaseConnectionError(
            f"Docker compose up failed (exit {exc.returncode}): {exc.stderr}"
        ) from exc
    except Exception as exc:
        raise OBaseConnectionError(f"Failed to execute docker compose: {exc}") from exc


def compose_down(
    *,
    compose_file: str,
    project_name: str | None = None,
    volumes: bool = False,
    remove_orphans: bool = True,
    docker_host: str = "unix:///var/run/docker.sock",
) -> dict[str, Any]:
    """docker-compose down."""
    if not os.path.exists(compose_file):
        raise OBaseNotFoundError(f"Compose file not found: {compose_file}")

    cmd = ["docker", "compose", "-f", compose_file]
    if project_name:
        cmd.extend(["-p", project_name])
    cmd.append("down")
    if volumes:
        cmd.append("-v")
    if remove_orphans:
        cmd.append("--remove-orphans")

    env = os.environ.copy()
    env["DOCKER_HOST"] = docker_host

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        return {"stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.CalledProcessError as exc:
        raise OBaseConnectionError(
            f"Docker compose down failed (exit {exc.returncode}): {exc.stderr}"
        ) from exc
    except Exception as exc:
        raise OBaseConnectionError(f"Failed to execute docker compose: {exc}") from exc


def docker_compose_pull(
    *,
    compose_file: str,
    project_name: str | None = None,
    docker_host: str = "unix:///var/run/docker.sock",
) -> dict[str, Any]:
    """docker compose pull — 预拉 compose 文件中所有服务镜像."""
    if not os.path.exists(compose_file):
        raise OBaseNotFoundError(f"Compose file not found: {compose_file}")

    cmd = ["docker", "compose", "-f", compose_file]
    if project_name:
        cmd.extend(["-p", project_name])
    cmd.append("pull")

    env = os.environ.copy()
    env["DOCKER_HOST"] = docker_host

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        return {"stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.CalledProcessError as exc:
        raise OBaseConnectionError(
            f"Docker compose pull failed (exit {exc.returncode}): {exc.stderr}"
        ) from exc
    except Exception as exc:
        raise OBaseConnectionError(f"Failed to execute docker compose pull: {exc}") from exc


# Aliases
docker_compose_up = compose_up
docker_compose_down = compose_down

__all__ = [
    "compose_up",
    "compose_down",
    "docker_compose_pull",
    "docker_compose_up",
    "docker_compose_down",
]
