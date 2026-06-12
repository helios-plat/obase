from __future__ import annotations

import io
from pathlib import Path

from pydantic import BaseModel


class MigrationResult(BaseModel):
    success: bool
    action: str
    current_revision: str | None
    message: str
    error: str | None = None


def run_migration(
    *,
    dsn: str,
    migrations_path: Path,
    action: str = "upgrade",
    target: str = "head",
) -> MigrationResult:
    """Run Alembic database migrations programmatically.

    Args:
        dsn: Database connection string (PostgreSQL DSN)
        migrations_path: Path to Alembic migrations directory (containing env.py)
        action: "upgrade" | "downgrade" | "history" | "current" | "stamp"
        target: Target revision (default "head")

    Returns:
        MigrationResult with current_revision and status

    Raises:
        ValueError: Unknown action

    Example:
        >>> result = run_migration(dsn="postgresql://...", migrations_path=Path("migrations"))
        >>> result.success
        True
    """
    allowed = {"upgrade", "downgrade", "history", "current", "stamp"}
    if action not in allowed:
        raise ValueError(f"Unknown migration action: {action!r}. Allowed: {allowed}")

    # Lazy imports: alembic + sqlalchemy are optional heavy deps; only loaded when called.
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_path))
    cfg.set_main_option("sqlalchemy.url", dsn)
    cfg.stdout = io.StringIO()

    try:
        if action == "upgrade":
            command.upgrade(cfg, target)
        elif action == "downgrade":
            command.downgrade(cfg, target)
        elif action == "history":
            command.history(cfg)
        elif action == "current":
            command.current(cfg)
        elif action == "stamp":
            command.stamp(cfg, target)

        engine = create_engine(dsn)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            rev = ctx.get_current_revision()
        engine.dispose()

        return MigrationResult(success=True, action=action, current_revision=rev, message="OK")
    except Exception as e:
        return MigrationResult(
            success=False,
            action=action,
            current_revision=None,
            message="failed",
            error=str(e),
        )
