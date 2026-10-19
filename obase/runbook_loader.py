"""obase.runbook_loader — parse a Runbook from YAML.

3O layer: obase (I/O and resources).
Matches the shape used by 3O_STATEFUL_EXECUTION_SPEC section 9 (the
coding-agent-loop example): top-level name/initial/version, a nodes mapping
keyed by node id, and an edges list.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from obase.exceptions import OBaseError
from obase.orchestrator import Check, CheckType, Edge, Node, Runbook


class RunbookParseError(OBaseError):
    retryable = False


def _stable_check_id(scope: str, check_type: CheckType, payload: dict[str, Any]) -> str:
    """Derive a reproducible check id from its position + content.

    YAML-declared checks have no natural identity of their own; without this,
    Check.id would fall back to a random uuid on every parse, making
    Runbook.content_hash() (and therefore start_runbook's resume check)
    unstable across reloads of the same unchanged file.
    """
    raw = json.dumps(
        {"scope": scope, "type": check_type.value, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def _parse_check(raw: dict[str, Any], scope: str) -> Check:
    try:
        check_type = CheckType(raw["type"])
    except KeyError as exc:
        raise RunbookParseError(f"check missing 'type': {raw!r}") from exc
    except ValueError as exc:
        raise RunbookParseError(f"unknown check type {raw.get('type')!r}: {raw!r}") from exc
    payload = raw.get("payload", {})
    kwargs: dict[str, Any] = {"type": check_type, "payload": payload}
    if "blocking" in raw:
        kwargs["blocking"] = bool(raw["blocking"])
    kwargs["id"] = raw.get("id") or _stable_check_id(scope, check_type, payload)
    return Check(**kwargs)


def _parse_node(node_id: str, raw: dict[str, Any]) -> Node:
    checks = [
        _parse_check(c, scope=f"{node_id}#before_transfer#{i}")
        for i, c in enumerate(raw.get("before_transfer", []))
    ]
    return Node(
        id=node_id,
        prompt=raw.get("prompt", ""),
        in_hook=raw.get("in_hook"),
        out_hook=raw.get("out_hook"),
        before_transfer=checks,
    )


def _parse_edge(raw: dict[str, Any]) -> Edge:
    try:
        from_node = raw["from"]
        to_node = raw["to"]
    except KeyError as exc:
        raise RunbookParseError(f"edge missing 'from'/'to': {raw!r}") from exc
    kwargs: dict[str, Any] = {"from_node": from_node, "to_node": to_node}
    if "condition" in raw:
        kwargs["condition"] = raw["condition"]
    if "hook" in raw:
        kwargs["hook"] = raw["hook"]
    if "max_attempts" in raw:
        kwargs["max_attempts"] = int(raw["max_attempts"])
    return Edge(**kwargs)


def parse_runbook(doc: dict[str, Any]) -> Runbook:
    """Build a Runbook from an already-parsed YAML/JSON-compatible dict."""
    try:
        name = doc["name"]
        initial = doc["initial"]
    except KeyError as exc:
        raise RunbookParseError(f"runbook missing required key: {exc}") from exc

    raw_nodes = doc.get("nodes", {})
    if not raw_nodes:
        raise RunbookParseError("runbook has no nodes")
    nodes = {node_id: _parse_node(node_id, raw or {}) for node_id, raw in raw_nodes.items()}
    if initial not in nodes:
        raise RunbookParseError(f"initial node {initial!r} not found in nodes: {sorted(nodes)}")

    edges = [_parse_edge(e) for e in doc.get("edges", [])]
    for e in edges:
        if e.from_node not in nodes:
            raise RunbookParseError(f"edge references unknown from-node: {e.from_node!r}")
        if e.to_node not in nodes:
            raise RunbookParseError(f"edge references unknown to-node: {e.to_node!r}")

    return Runbook(
        name=name,
        initial=initial,
        nodes=nodes,
        edges=edges,
        version=str(doc.get("version", "1")),
    )


def load_runbook_yaml(path: Path | str) -> Runbook:
    """Load and parse a Runbook definition from a YAML file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunbookParseError(f"runbook file not found: {path}") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RunbookParseError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise RunbookParseError(
            f"{path}: top-level YAML must be a mapping, got {type(doc).__name__}"
        )
    return parse_runbook(doc)
