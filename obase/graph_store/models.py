"""obase.graph_store — MVCC fact nodes + in-memory pool. No Veya routing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class FactNode(BaseModel):
    node_id: str
    subject: str
    predicate: str
    object_value: str
    valid_from: datetime
    valid_to: datetime | None = None
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"
    evidence_id: str = ""


class ExperienceItem(BaseModel):
    item_id: str
    file_path: str
    category: str
    summary: str
    created_at: datetime = Field(default_factory=_now)


class GraphDBPool:
    """In-process MVCC store. A later adapter can talk to Postgres/pgvector."""

    def __init__(self) -> None:
        self.facts: dict[str, FactNode] = {}
        self.experiences: list[ExperienceItem] = []

    def find_active(self, subject: str, *, predicate: str) -> FactNode | None:
        for fact in self.facts.values():
            if (
                fact.status == "ACTIVE"
                and fact.subject == subject
                and fact.predicate == predicate
            ):
                return fact
        return None

    async def upsert_and_archive(
        self,
        new_fact: FactNode,
        old_fact_id: str | None = None,
    ) -> None:
        if old_fact_id and old_fact_id in self.facts:
            old = self.facts[old_fact_id]
            self.facts[old_fact_id] = old.model_copy(
                update={"status": "ARCHIVED", "valid_to": new_fact.valid_from}
            )
        self.facts[new_fact.node_id] = new_fact

    async def append_experience(self, item: ExperienceItem) -> None:
        self.experiences.append(item)

    def snapshot(self) -> dict[str, Any]:
        return {
            "facts": [f.model_dump(mode="json") for f in self.facts.values()],
            "experiences": [e.model_dump(mode="json") for e in self.experiences],
        }


def new_fact(
    subject: str,
    *,
    predicate: str,
    object_value: str,
    evidence_id: str = "",
) -> FactNode:
    return FactNode(
        node_id=uuid4().hex,
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        valid_from=_now(),
        evidence_id=evidence_id,
    )
