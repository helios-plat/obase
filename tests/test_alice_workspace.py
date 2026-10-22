from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from obase.alice_workspace import ResearchWorkspace, WorkspaceError


def test_workspace_persists_artifact_hash_and_git_head(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Alice Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "alice@example.invalid"], check=True)
    (tmp_path / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"], check=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    workspace = ResearchWorkspace(tmp_path)
    metadata = workspace.initialize("btc-thesis", "BTC thesis")
    record = workspace.save_document("research/btc.md", "BTC thesis", "A sourced view.\n", source_refs=["https://example.invalid/source"])

    assert metadata["workspace_id"] == "btc-thesis"
    assert (tmp_path / "research/btc.md").read_text(encoding="utf-8") == "A sourced view.\n"
    assert record["sha256"] == hashlib.sha256(b"A sourced view.\n").hexdigest()
    assert record["git_head"] == head
    assert workspace.list_artifacts() == [record]
    assert json.loads((tmp_path / ".alice/artifacts.jsonl").read_text(encoding="utf-8")) == record


def test_workspace_is_idempotent_but_metadata_is_immutable(tmp_path: Path) -> None:
    workspace = ResearchWorkspace(tmp_path)
    first = workspace.initialize("macro-weekly", "Weekly macro")
    assert workspace.initialize("macro-weekly", "Weekly macro") == first
    with pytest.raises(WorkspaceError, match="immutable"):
        workspace.initialize("macro-weekly", "Renamed")
    with pytest.raises(WorkspaceError, match="different id"):
        workspace.initialize("another-id", "Weekly macro")


@pytest.mark.parametrize("path", ["../escape.md", "/tmp/escape.md", "research/../../escape.md", ".alice/workspace.json", r"research\\escape.md"])
def test_unsafe_artifact_paths_are_rejected(tmp_path: Path, path: str) -> None:
    workspace = ResearchWorkspace(tmp_path)
    workspace.initialize("safe-workspace", "Safe")
    with pytest.raises(WorkspaceError):
        workspace.save_document(path, "bad", "not written")


def test_symlink_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace_root.mkdir()
    outside.mkdir()
    (workspace_root / "external").symlink_to(outside, target_is_directory=True)
    workspace = ResearchWorkspace(workspace_root)
    workspace.initialize("safe-workspace", "Safe")
    with pytest.raises(WorkspaceError, match="escapes"):
        workspace.save_document("external/secret.md", "secret", "must not be written")
    assert not (outside / "secret.md").exists()
