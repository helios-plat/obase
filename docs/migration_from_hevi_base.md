# Migration from hevi.base to obase

This document covers every breaking change and new feature you need to know when migrating from `hevi.base` to `obase`.

## 1. Exception hierarchy

**Before (hevi.base):** All exceptions inherit from `HeviError`.

**After (obase):** All exceptions inherit from `OBaseError`.

```python
# Before
from hevi.base.exceptions import HeviError, BudgetExceeded

# After
from obase.exceptions import OBaseError, BudgetExceeded
```

Every exception now carries a `retryable: bool` class attribute:
- `retryable=True`: `CacheError`, `RateLimitExceeded`
- `retryable=False`: everything else

---

## 2. working_dir default path

| Library     | Default                     |
|-------------|-----------------------------|
| hevi.base   | `~/hevi_work/`              |
| obase       | `~/.obase/work/`            |

---

## 3. Trail.emit signature change

**Before:** First positional arg was an enum member; extra data nested under `"data"` key.

**After:** First positional arg is a free-form `event: str`; all `**kwargs` are flattened into the top-level JSON object.

```python
# Before
trail.emit(TrailEvent.STAGE_DONE, data={"elapsed": 1.2})
# → {"event": "STAGE_DONE", "data": {"elapsed": 1.2}}

# After
trail.emit("stage_done", elapsed=1.2)
# → {"event": "stage_done", "elapsed": 1.2}
```

`query_trail()` is a new function that scans across multiple runs:

```python
from obase.trail import query_trail
events = query_trail(event_type="stage_done", run_id_pattern="run-2026")
```

---

## 4. CostTracker strict_pricing

`CostTracker` gains `strict_pricing: bool = True`.

| Mode        | Missing price entry behavior                          |
|-------------|-------------------------------------------------------|
| `True` (default) | Raises `PricingNotConfiguredError`             |
| `False`          | Records $0, emits `pricing_missing` trail event, logs WARNING |

```python
# Lenient mode (matches old hevi behavior)
ct = CostTracker(pricing_table=table, strict_pricing=False)
```

`PricingNotConfiguredError` carries `.category`, `.provider`, `.model_or_tier`, `.unit` attributes.

`PricingTable` is now a Pydantic `BaseModel` (was a plain dict). Load from YAML via `PricingTable.from_yaml(path)`.

---

## 5. Stage: input_keys / output_keys

Stages now support explicit I/O contracts:

```python
Stage(
    name="my_stage",
    func=my_func,
    input_keys=["prompt", "context"],   # None = receive full dict (compat mode)
    output_keys=["response"],           # None = return anything (compat mode)
)
```

- `input_keys=None` / `output_keys=None` → backward-compatible (full dict in/out)
- Non-`None` → strict enforcement; violations raise `StageContractViolation`

---

## 6. RunState fields

| Removed               | Added                                    |
|-----------------------|------------------------------------------|
| `metadata` (nested)   | Fields flattened to top level            |
|                       | `paused_at_stage: str \| None`           |
|                       | `started_at: datetime`                   |
|                       | `current_stage_index: int`               |

---

## 7. PauseRequested + resume_data

Stage functions can pause the pipeline by raising `PauseRequested`:

```python
raise PauseRequested("need human input", resume_data={"form_url": "https://..."})
```

The orchestrator merges `resume_data` into `RunState.data`, sets `state="paused"`, saves state, and **returns** (does not raise to the caller).

Resume a paused pipeline:

```python
state = await run_pipeline(pipeline, run_id=existing_run_id, resume=True)
```

---

## 8. run_pipeline signature

```python
# New optional parameters
await run_pipeline(pipeline, initial_data={}, trail=my_trail, cost=my_cost)
```

If `trail` or `cost` are `None`, the orchestrator creates internal instances automatically.

---

## 9. RateLimitRegistry

The module-level `load_from_yaml()` function is replaced by a class with classmethods:

```python
# Before
from hevi.base.rate_limit import load_from_yaml
load_from_yaml(path)

# After
from obase.rate_limit import RateLimitRegistry
RateLimitRegistry.load_from_yaml(path)
rl = RateLimitRegistry.get("my-api")
```

---

## 10. bootstrap module (new)

```python
from obase.bootstrap import bootstrap, load_env

# One-liner init
bootstrap(
    env_path=Path(".env"),
    working_dir=Path("/data/runs"),
    auto_discover_providers=True,
    logger_level="INFO",
)

# Just load .env
injected = load_env(Path(".env"), strict=True)
```

`load_env` extras vs plain `dotenv`:
- Strips inline `# comments`
- Skips empty values (no `KEY=` → no empty string in `os.environ`)
- Validates `*_URL` / `*_BASE_URL` keys have scheme + host
