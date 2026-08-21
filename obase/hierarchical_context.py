"""obase.hierarchical_context — 3o:// URI-addressed, layered (L0/L1/L2) context store.

3O layer: obase (I/O and resources).
Implements the HierarchicalContext conventions from 3O_STATEFUL_EXECUTION_SPEC
section 8: every URI may carry an L0 ``.abstract`` (<=120 tokens) and an L1
``.overview`` (<=2048 tokens) sidecar next to its L2 body (the original
content, loaded on demand only). Generating the abstract/overview text is the
caller's job (an LLM, a human, a template) — this module only enforces the
storage layout, the token budgets, and an observable retrieve() helper that
never reads L2 on its own.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obase.exceptions import OBaseError
from obase.sandbox.path_jail import PathJail
from obase.token_counter import token_counter

URI_SCHEME = "3o://"
L0_MAX_TOKENS = 120
L1_MAX_TOKENS = 2048

_LAYER_SUFFIX = {"L0": ".abstract", "L1": ".overview"}


class HierarchicalContextError(OBaseError):
    retryable = False


class TokenBudgetExceeded(HierarchicalContextError):
    def __init__(self, layer: str, limit: int, actual: int) -> None:
        super().__init__(f"{layer} budget exceeded: {actual} tokens > {limit} limit")
        self.layer = layer
        self.limit = limit
        self.actual = actual


def _strip_scheme(uri: str) -> str:
    if not uri.startswith(URI_SCHEME):
        raise HierarchicalContextError(f"not a {URI_SCHEME} URI: {uri!r}")
    return uri[len(URI_SCHEME) :]


class HierarchicalContextStore:
    def __init__(self, root: Path | str | None = None) -> None:
        raw_root = Path(
            root or os.environ.get("THREE_O_CONTEXT_DIR", Path.home() / ".local/state/3o/context")
        )
        raw_root.mkdir(parents=True, exist_ok=True)
        self._jail = PathJail(raw_root)
        self.root = self._jail.root

    def _path(self, uri: str) -> Path:
        return self._jail.resolve_and_verify(_strip_scheme(uri))

    def _sidecar(self, path: Path, layer: str) -> Path:
        return path.parent / f"{path.name}{_LAYER_SUFFIX[layer]}"

    def _target(self, uri: str, layer: str) -> Path:
        path = self._path(uri)
        return path if layer == "L2" else self._sidecar(path, layer)

    def write(
        self,
        uri: str,
        content: str,
        *,
        abstract: str | None = None,
        overview: str | None = None,
    ) -> None:
        """Write the L2 body, optionally alongside its L0/L1 sidecars."""
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if abstract is not None:
            self.set_abstract(uri, abstract)
        if overview is not None:
            self.set_overview(uri, overview)

    def set_abstract(self, uri: str, text: str) -> None:
        self._write_layer(uri, "L0", text, L0_MAX_TOKENS)

    def set_overview(self, uri: str, text: str) -> None:
        self._write_layer(uri, "L1", text, L1_MAX_TOKENS)

    def _write_layer(self, uri: str, layer: str, text: str, limit: int) -> None:
        n = token_counter(text)
        if n > limit:
            raise TokenBudgetExceeded(layer, limit, n)
        target = self._target(uri, layer)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def read(self, uri: str, layer: str = "L2") -> str:
        target = self._target(uri, layer)
        if not target.exists():
            raise FileNotFoundError(f"{layer} not found for {uri}")
        return target.read_text(encoding="utf-8")

    def exists(self, uri: str, layer: str = "L2") -> bool:
        return self._target(uri, layer).exists()

    def list_uris(self, prefix: str) -> list[str]:
        """List L2 entries (files, not sidecars/dirs) under a 3o:// prefix."""
        base = self._path(prefix)
        if base.is_file():
            return [prefix]
        if not base.is_dir():
            return []
        out = []
        for p in sorted(base.rglob("*")):
            if p.is_dir() or p.suffix in _LAYER_SUFFIX.values():
                continue
            rel = p.relative_to(self.root).as_posix()
            out.append(f"{URI_SCHEME}{rel}")
        return out


@dataclass
class RetrievalStep:
    uri: str
    layer: str
    score: float
    reason: str


@dataclass
class RetrievalResult:
    items: list[dict[str, Any]]
    trajectory: list[RetrievalStep] = field(default_factory=list)
    tokens_used: int = 0


Scorer = Callable[[str, str], float]


def retrieve(
    store: HierarchicalContextStore,
    query: str,
    candidate_uris: list[str],
    scorer: Scorer,
    *,
    top_k: int = 5,
    escalate_threshold: float = 0.5,
) -> RetrievalResult:
    """Score candidates against their L0 abstract; escalate to L1 above threshold.

    L2 is never read here — the caller fetches it explicitly via
    ``store.read(uri, "L2")`` once an item is actually needed. ``scorer`` is
    caller-supplied (embedding similarity, an LLM call, a keyword match —
    this module has no opinion) so the trajectory stays fully observable
    without obase depending on any particular retrieval backend.
    """
    trajectory: list[RetrievalStep] = []
    scored: list[tuple[float, str, str, str]] = []
    tokens_used = 0

    for uri in candidate_uris:
        if not store.exists(uri, "L0"):
            trajectory.append(
                RetrievalStep(uri=uri, layer="L0", score=0.0, reason="no L0 abstract")
            )
            continue

        l0_text = store.read(uri, "L0")
        tokens_used += token_counter(l0_text)
        l0_score = scorer(query, l0_text)
        trajectory.append(
            RetrievalStep(uri=uri, layer="L0", score=l0_score, reason="scored abstract")
        )

        layer, text, score = "L0", l0_text, l0_score
        if l0_score >= escalate_threshold and store.exists(uri, "L1"):
            l1_text = store.read(uri, "L1")
            tokens_used += token_counter(l1_text)
            l1_score = scorer(query, l1_text)
            trajectory.append(
                RetrievalStep(
                    uri=uri, layer="L1", score=l1_score, reason="escalated past threshold"
                )
            )
            layer, text, score = "L1", l1_text, l1_score

        scored.append((score, uri, layer, text))

    scored.sort(key=lambda t: t[0], reverse=True)
    items = [{"uri": u, "layer": layer, "score": s, "text": t} for s, u, layer, t in scored[:top_k]]
    return RetrievalResult(items=items, trajectory=trajectory, tokens_used=tokens_used)
