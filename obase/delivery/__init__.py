"""obase delivery layer — atomic batch claim / release / ack helpers.

3O layer: obase (cross-cutting infrastructure).

See :mod:`obase.delivery.claim` for the lease mechanism and the
:func:`~obase.delivery.claim.register_claimable_table` allow-list contract.
"""

from __future__ import annotations

from obase.delivery.claim import (
    DEFAULT_ALLOWED_TABLES,
    DEFAULT_CLAIM_COLUMNS,
    ack,
    claim_batch,
    register_claimable_table,
    registered_claim_columns,
    release,
)

__all__ = [
    "DEFAULT_ALLOWED_TABLES",
    "DEFAULT_CLAIM_COLUMNS",
    "ack",
    "claim_batch",
    "register_claimable_table",
    "registered_claim_columns",
    "release",
]
