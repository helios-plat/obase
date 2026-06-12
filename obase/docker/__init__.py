"""obase.docker — Docker container/image/compose operations.

Migrated from oprim._docker. Uses obase.exceptions instead of oprim._exceptions.
oprim._docker is not deleted (deprecated; removal in batch-4/oprim v3.0.0).
"""

from __future__ import annotations

from obase.docker.client import (
    ContainerCreateResult,
    ContainerExecResult,
    ContainerInfo,
    ContainerOpResult,
    ContainerRenameResult,
    ContainerStats,
    ImagePullResult,
    LogLine,
    NetworkCreateResult,
    NetworkDeleteResult,
    NodeInfo,
    PruneResult,
    VolumeCreateResult,
)
from obase.docker.compose import (
    compose_down,
    compose_up,
    docker_compose_down,
    docker_compose_pull,
    docker_compose_up,
)
from obase.docker.containers import (
    docker_container_create,
    docker_container_exec,
    docker_container_inspect,
    docker_container_list,
    docker_container_logs,
    docker_container_rename,
    docker_container_restart,
    docker_container_start,
    docker_container_stats,
    docker_container_stop,
)
from obase.docker.images import (
    docker_image_delete,
    docker_image_list,
    docker_image_pull,
    docker_system_prune,
)
from obase.docker.networks import (
    docker_network_create,
    docker_network_delete,
    docker_network_list,
    docker_node_info,
)
from obase.docker.volumes import (
    docker_volume_create,
    docker_volume_delete,
    docker_volume_list,
)

# Short-name aliases (matches oprim._docker alias surface)
docker_logs = docker_container_logs
docker_ps = docker_container_list
docker_restart = docker_container_restart
docker_stats = docker_container_stats
docker_inspect = docker_container_inspect

__all__ = [
    # Models
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
    # Container ops
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
    # Image ops
    "docker_image_pull",
    "docker_image_list",
    "docker_image_delete",
    "docker_system_prune",
    # Network ops
    "docker_network_list",
    "docker_network_create",
    "docker_network_delete",
    "docker_node_info",
    # Volume ops
    "docker_volume_list",
    "docker_volume_delete",
    "docker_volume_create",
    # Compose ops
    "compose_up",
    "compose_down",
    "docker_compose_pull",
    "docker_compose_up",
    "docker_compose_down",
    # Aliases
    "docker_logs",
    "docker_ps",
    "docker_restart",
    "docker_stats",
    "docker_inspect",
]
