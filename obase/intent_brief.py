"""obase.intent_brief — G0 contractor brief. Data only, no I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IntentAction = Literal["plan", "ask", "refuse"]


class IntentBrief(BaseModel):
    """Authoritative restatement of what to dispatch. Not the raw user sentence."""

    action: IntentAction = "ask"
    interpretation: str = ""
    in_scope_files: list[str] = Field(default_factory=list)
    out_of_scope_files: list[str] = Field(default_factory=list)
    acceptance_draft: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
