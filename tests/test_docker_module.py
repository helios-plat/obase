"""Tests for obase.docker — docker module (mock docker client)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from obase.docker import (
    ContainerCreateResult,
    ContainerExecResult,
    ContainerInfo,
    ContainerOpResult,
    ContainerStats,
    ImagePullResult,
    LogLine,
    NetworkCreateResult,
    NetworkDeleteResult,
    NodeInfo,
    PruneResult,
    VolumeCreateResult,
    compose_down,
    compose_up,
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
    docker_image_delete,
    docker_image_list,
    docker_image_pull,
    docker_inspect,
    docker_logs,
    docker_network_create,
    docker_network_delete,
    docker_network_list,
    docker_node_info,
    docker_ps,
    docker_restart,
    docker_stats,
    docker_system_prune,
    docker_volume_create,
    docker_volume_delete,
    docker_volume_list,
)
from obase.exceptions import OBaseConnectionError, OBaseNotFoundError, OBaseValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_ATTRS = {
    "Id": "abc123",
    "Name": "/mycontainer",
    "State": {
        "Status": "running",
        "StartedAt": "2026-06-01T10:00:00Z",
        "FinishedAt": "0001-01-01T00:00:00Z",
        "ExitCode": 0,
        "Health": None,
    },
    "Config": {"Image": "nginx:latest", "Labels": {}},
    "RestartCount": 0,
    "HostConfig": {"PortBindings": {}},
    "Mounts": [],
}


def _make_container(status: str = "running", attrs: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.id = "abc123"
    c.name = "mycontainer"
    c.status = status
    c.reload = MagicMock()
    c.attrs = {**_BASE_ATTRS, **(attrs or {})}
    c.attrs["State"] = {**_BASE_ATTRS["State"], "Status": status}
    return c


def _mock_client(container: MagicMock | None = None) -> MagicMock:
    client = MagicMock()
    if container is not None:
        client.containers.get.return_value = container
    return client


PATCH_CLIENT = "obase.docker.client.docker.DockerClient"


# ---------------------------------------------------------------------------
# Aliases smoke test
# ---------------------------------------------------------------------------


def test_aliases_point_to_correct_functions():
    assert docker_logs is docker_container_logs
    assert docker_ps is docker_container_list
    assert docker_restart is docker_container_restart
    assert docker_stats is docker_container_stats
    assert docker_inspect is docker_container_inspect


# ---------------------------------------------------------------------------
# docker_container_inspect
# ---------------------------------------------------------------------------


class TestDockerContainerInspect:
    def test_running_container(self):
        c = _make_container("running")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_inspect(container_id="abc123")
        assert isinstance(result, ContainerInfo)
        assert result.state == "running"
        assert result.container_id == "abc123"

    def test_health_check_parsed(self):
        c = _make_container("running")
        c.attrs["State"]["Health"] = {"Status": "healthy"}
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_inspect(container_id="abc123")
        assert result.health == "healthy"

    def test_not_found_raises(self):
        import docker.errors

        client = MagicMock()
        client.containers.get.side_effect = docker.errors.NotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_container_inspect(container_id="missing")

    def test_finished_at_zeroed_becomes_none(self):
        c = _make_container("exited")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_inspect(container_id="abc123")
        assert result.finished_at is None


# ---------------------------------------------------------------------------
# docker_container_start / stop / restart
# ---------------------------------------------------------------------------


class TestContainerLifecycle:
    def test_start_returns_op_result(self):
        c = _make_container("exited")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_start(container_id="abc123")
        assert isinstance(result, ContainerOpResult)
        assert result.operation == "start"
        assert result.success is True

    def test_stop_returns_op_result(self):
        c = _make_container("running")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_stop(container_id="abc123")
        assert result.operation == "stop"

    def test_restart_returns_op_result(self):
        c = _make_container("running")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_restart(container_id="abc123")
        assert result.operation == "restart"

    def test_start_connection_error_on_docker_exc(self):
        import docker.errors

        c = _make_container("exited")
        c.start.side_effect = docker.errors.DockerException("boom")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            with pytest.raises(OBaseConnectionError):
                docker_container_start(container_id="abc123")


# ---------------------------------------------------------------------------
# docker_container_logs
# ---------------------------------------------------------------------------


class TestDockerContainerLogs:
    def test_parses_log_lines(self):
        c = _make_container()
        c.logs.return_value = b"2026-06-01T10:00:00Z hello world\n2026-06-01T10:00:01Z second\n"
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_logs(container_id="abc123")
        assert len(result) == 2
        assert all(isinstance(line, LogLine) for line in result)
        assert result[0].message == "hello world"

    def test_empty_logs(self):
        c = _make_container()
        c.logs.return_value = b""
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_logs(container_id="abc123")
        assert result == []


# ---------------------------------------------------------------------------
# docker_container_stats
# ---------------------------------------------------------------------------


class TestDockerContainerStats:
    def test_stats_parsed(self):
        c = _make_container()
        c.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [100, 100]},
                "system_cpu_usage": 2000,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
            "memory_stats": {"usage": 512 * 1024, "limit": 1024 * 1024},
            "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 500}},
            "blkio_stats": {"io_service_bytes_recursive": []},
            "pids_stats": {"current": 5},
        }
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_stats(container_id="abc123")
        assert isinstance(result, ContainerStats)
        assert result.cpu_percent >= 0
        assert result.memory_usage_bytes == 512 * 1024
        assert result.network_rx_bytes == 1000
        assert result.pids == 5


# ---------------------------------------------------------------------------
# docker_image_pull
# ---------------------------------------------------------------------------


class TestDockerImagePull:
    def test_pull_new_image(self):
        import docker.errors

        client = MagicMock()
        client.images.get.side_effect = docker.errors.ImageNotFound("nope")
        img = MagicMock()
        img.id = "sha256:abc"
        img.attrs = {"Size": 100_000}
        client.images.pull.return_value = img
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_image_pull(image="nginx", tag="latest")
        assert isinstance(result, ImagePullResult)
        assert result.pulled is True

    def test_image_already_local(self):
        client = MagicMock()
        img = MagicMock()
        img.id = "sha256:abc"
        img.attrs = {"Size": 100_000}
        client.images.get.return_value = img
        client.images.pull.return_value = img
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_image_pull(image="nginx", tag="latest")
        assert result.pulled is False

    def test_image_not_found_raises(self):
        import docker.errors

        client = MagicMock()
        client.images.get.side_effect = docker.errors.ImageNotFound("nope")
        client.images.pull.side_effect = docker.errors.ImageNotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_image_pull(image="nonexistent:xyz")


# ---------------------------------------------------------------------------
# docker_container_list
# ---------------------------------------------------------------------------


class TestDockerContainerList:
    def test_returns_list_of_container_info(self):
        c = _make_container()
        c.image = MagicMock()
        c.image.tags = ["nginx:latest"]
        client = MagicMock()
        client.containers.list.return_value = [c]
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_container_list()
        assert len(result) == 1
        assert isinstance(result[0], ContainerInfo)

    def test_empty_list(self):
        client = MagicMock()
        client.containers.list.return_value = []
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_container_list()
        assert result == []


# ---------------------------------------------------------------------------
# docker_container_create
# ---------------------------------------------------------------------------


class TestDockerContainerCreate:
    def test_create_returns_result(self):
        c = MagicMock()
        c.id = "new123"
        c.name = "myapp"
        c.attrs = {"Warnings": []}
        client = MagicMock()
        client.containers.create.return_value = c
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_container_create(image="nginx:latest", name="myapp")
        assert isinstance(result, ContainerCreateResult)
        assert result.container_id == "new123"

    def test_image_not_found_raises(self):
        import docker.errors

        client = MagicMock()
        client.containers.create.side_effect = docker.errors.ImageNotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_container_create(image="nonexistent", name="test")


# ---------------------------------------------------------------------------
# docker_container_rename
# ---------------------------------------------------------------------------


class TestDockerContainerRename:
    def test_rename_success(self):
        c = _make_container()
        c.name = "/oldname"
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_rename(container_id="abc123", new_name="newname")
        assert result.old_name == "oldname"
        assert result.new_name == "newname"

    def test_conflict_raises_validation_error(self):
        import docker.errors

        c = _make_container()
        c.name = "/oldname"
        c.rename.side_effect = docker.errors.APIError("Conflict: already in use")
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            with pytest.raises(OBaseValidationError):
                docker_container_rename(container_id="abc123", new_name="taken")


# ---------------------------------------------------------------------------
# docker_container_exec
# ---------------------------------------------------------------------------


class TestDockerContainerExec:
    def test_exec_success(self):
        c = _make_container()
        c.exec_run.return_value = (0, (b"hello", b""))
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_exec(container_id="abc123", command=["echo", "hello"])
        assert isinstance(result, ContainerExecResult)
        assert result.exit_code == 0
        assert result.stdout == "hello"

    def test_exec_with_stderr(self):
        c = _make_container()
        c.exec_run.return_value = (1, (b"", b"error msg"))
        with patch(PATCH_CLIENT, return_value=_mock_client(c)):
            result = docker_container_exec(container_id="abc123", command=["bad"])
        assert result.exit_code == 1
        assert result.stderr == "error msg"


# ---------------------------------------------------------------------------
# docker_image_list / docker_image_delete
# ---------------------------------------------------------------------------


class TestDockerImages:
    def test_image_list(self):
        img = MagicMock()
        img.id = "sha256:abc"
        img.tags = ["nginx:latest"]
        img.attrs = {"Size": 50_000, "Created": "2026-01-01"}
        client = MagicMock()
        client.images.list.return_value = [img]
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_image_list()
        assert len(result) == 1
        assert result[0]["tags"] == ["nginx:latest"]

    def test_image_delete_not_found_raises(self):
        import docker.errors

        client = MagicMock()
        client.images.remove.side_effect = docker.errors.ImageNotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_image_delete(image="gone:latest")


# ---------------------------------------------------------------------------
# docker_network_*
# ---------------------------------------------------------------------------


class TestDockerNetworks:
    def test_network_list(self):
        net = MagicMock()
        net.id = "net1"
        net.name = "bridge"
        net.attrs = {"Driver": "bridge", "Scope": "local", "Internal": False}
        client = MagicMock()
        client.networks.list.return_value = [net]
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_network_list()
        assert len(result) == 1
        assert result[0]["name"] == "bridge"

    def test_network_create(self):
        net = MagicMock()
        net.id = "net123"
        net.name = "mynet"
        net.attrs = {"Driver": "bridge"}
        client = MagicMock()
        client.networks.create.return_value = net
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_network_create(name="mynet")
        assert isinstance(result, NetworkCreateResult)
        assert result.name == "mynet"

    def test_network_delete(self):
        net = MagicMock()
        net.name = "mynet"
        client = MagicMock()
        client.networks.get.return_value = net
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_network_delete(network_id="net123")
        assert isinstance(result, NetworkDeleteResult)
        assert result.deleted is True

    def test_network_delete_not_found(self):
        import docker.errors

        client = MagicMock()
        client.networks.get.side_effect = docker.errors.NotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_network_delete(network_id="ghost")


# ---------------------------------------------------------------------------
# docker_volume_*
# ---------------------------------------------------------------------------


class TestDockerVolumes:
    def test_volume_list(self):
        vol = MagicMock()
        vol.name = "mydata"
        vol.attrs = {"Driver": "local", "Mountpoint": "/data", "CreatedAt": "", "Labels": {}}
        client = MagicMock()
        client.volumes.list.return_value = [vol]
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_volume_list()
        assert len(result) == 1
        assert result[0]["name"] == "mydata"

    def test_volume_create(self):
        vol = MagicMock()
        vol.name = "newvol"
        vol.attrs = {"Driver": "local", "Mountpoint": "/x", "CreatedAt": "2026-01-01"}
        client = MagicMock()
        client.volumes.create.return_value = vol
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_volume_create(name="newvol")
        assert isinstance(result, VolumeCreateResult)
        assert result.name == "newvol"

    def test_volume_delete_not_found(self):
        import docker.errors

        client = MagicMock()
        client.volumes.get.side_effect = docker.errors.NotFound("nope")
        with patch(PATCH_CLIENT, return_value=client):
            with pytest.raises(OBaseNotFoundError):
                docker_volume_delete(name="ghost")


# ---------------------------------------------------------------------------
# docker_system_prune
# ---------------------------------------------------------------------------


class TestDockerSystemPrune:
    def test_prune_returns_result(self):
        client = MagicMock()
        client.containers.prune.return_value = {"ContainersDeleted": ["c1"], "SpaceReclaimed": 100}
        client.images.prune.return_value = {"ImagesDeleted": [], "SpaceReclaimed": 0}
        with patch(PATCH_CLIENT, return_value=client):
            result = docker_system_prune()
        assert isinstance(result, PruneResult)
        assert result.containers_removed == 1


# ---------------------------------------------------------------------------
# docker_node_info
# ---------------------------------------------------------------------------


class TestDockerNodeInfo:
    def test_reachable_node(self):
        client = MagicMock()
        client.info.return_value = {
            "OperatingSystem": "Linux",
            "Architecture": "x86_64",
            "NCPU": 4,
            "MemTotal": 8_000_000_000,
            "ContainersRunning": 2,
        }
        client.version.return_value = {"Version": "24.0.0"}
        with patch("obase.docker.networks.docker.DockerClient", return_value=client):
            result = docker_node_info(docker_host="tcp://1.2.3.4:2375")
        assert isinstance(result, NodeInfo)
        assert result.reachable is True
        assert result.cpus == 4

    def test_unreachable_node_returns_reachable_false(self):
        with patch(
            "obase.docker.networks.docker.DockerClient",
            side_effect=Exception("connection refused"),
        ):
            result = docker_node_info(docker_host="tcp://1.2.3.4:2375")
        assert result.reachable is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# compose_up / compose_down (file-not-found path)
# ---------------------------------------------------------------------------


class TestCompose:
    def test_compose_up_file_not_found(self):
        with pytest.raises(OBaseNotFoundError):
            compose_up(compose_file="/nonexistent/docker-compose.yml")

    def test_compose_down_file_not_found(self):
        with pytest.raises(OBaseNotFoundError):
            compose_down(compose_file="/nonexistent/docker-compose.yml")
