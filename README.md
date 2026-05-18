# obase

Helios ecosystem cross-cutting infrastructure library. Provides orchestration, observability, cost tracking, caching, rate limiting, and provider management as composable building blocks.

## Modules

| Module              | Purpose                                               |
|---------------------|-------------------------------------------------------|
| `orchestrator`      | Stage-based async pipeline with retry, pause, resume  |
| `trail`             | Append-only structured event log (JSONL)              |
| `cost_tracker`      | Usage recording + budget enforcement + Pydantic pricing table |
| `fs`                | Working directory management, file hashing, cleanup   |
| `cache`             | Pickle-backed async cache with TTL                    |
| `rate_limit`        | Sliding-window rate limiter + named registry           |
| `provider_registry` | (category, name) → callable registry + entry points  |
| `bootstrap`         | One-shot init: load_env + working_dir + providers + logging |

## Quick start

```python
from obase.bootstrap import bootstrap
from obase.orchestrator import Pipeline, Stage, run_pipeline

bootstrap(auto_discover_providers=False)

async def my_stage(data: dict, ctx) -> dict:
    return {"result": data["input"] * 2}

pipeline = Pipeline("demo", [Stage("double", my_stage)])
state = await run_pipeline(pipeline, initial_data={"input": 21})
print(state.data["result"])  # 42
```

## Installation

```bash
pip install obase
```

## Requirements

- Python 3.12+
- pydantic >= 2.0
- pyyaml >= 6.0
- tenacity >= 8.0
- structlog >= 24.0

## Design

See [docs/design_principles.md](docs/design_principles.md).

Migrating from hevi.base? See [docs/migration_from_hevi_base.md](docs/migration_from_hevi_base.md).
