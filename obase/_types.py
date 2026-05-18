from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OBaseModel(BaseModel):
    """Shared Pydantic base for all obase models."""

    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        populate_by_name=True,
    )
