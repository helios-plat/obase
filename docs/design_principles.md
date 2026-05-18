# obase Design Principles

## 1. Fail loud, never fail silent

Every error path in obase raises an exception or returns a clearly invalid value. There are no silent suppressions, empty fallbacks, or "best-effort" behaviors that swallow errors.

Concrete rules:

- `Cache.put()` failure → `CacheError` (never suppressed)
- `Cache.get()` miss → `None` (expected, not an error)
- `Cache.get()` corrupt file → `CacheError`
- `ProviderRegistry.get()` miss → `ProviderNotFoundError`
- `CostTracker.record()` missing pricing, `strict=True` → `PricingNotConfiguredError`
- `RateLimitRegistry.get()` miss → `OBaseError`

The one intentional "fail soft" mode is `CostTracker(strict_pricing=False)`, which is opt-in and logs a WARNING + emits a `pricing_missing` trail event so the deviation is always visible.

## 2. Observable by default

Every significant event emits a structured trail record. Trail events are flat JSON objects (no nesting), making them trivially grep-able and queryable with `query_trail()`.

All internal structlog calls use the `obase.<module>.<event>` naming convention.

## 3. Composable injection

The orchestrator accepts `trail` and `cost` as optional parameters. When omitted, internal instances are created automatically. This design lets callers:

- Share a single `Trail` / `CostTracker` across multiple pipelines
- Inject test doubles without monkeypatching
- Use the orchestrator in isolation without any external infrastructure

## 4. Explicit I/O contracts (opt-in)

Stage `input_keys` / `output_keys` enable gradual strictness. New code should define both; legacy code passes `None` to stay in compat mode.

Strict mode prevents "data dict sprawl" — a common failure pattern where stages accumulate unrelated keys and it becomes unclear what data flows where.

## 5. Pause is a first-class primitive

Human-in-the-loop workflows are not afterthoughts. Any stage can `raise PauseRequested(reason, resume_data={...})` and the orchestrator will persist state and return gracefully. The calling process can exit entirely; a separate process resumes by calling `run_pipeline(..., resume=True)`.

Resume data is merged into `RunState.data` before the paused stage re-executes, allowing the human's decision to influence the stage's behavior.

## 6. Registry pattern for extensibility

`ProviderRegistry` and `RateLimitRegistry` use class-level dicts rather than module globals or singletons. This makes them:

- Easy to clear in tests (`.clear()` classmethod)
- Discoverable via Python entry points (`obase.providers` group)
- Safely namespaced by `(category, name)` tuples

## 7. Pydantic for structured config

`PricingTable`, `PricingEntry`, and `OBaseModel` use Pydantic v2. YAML-loaded config is validated at load time, not at first use. Misconfigured pricing tables fail immediately when loaded, not when money is first spent.

## 8. Async throughout

All I/O-adjacent operations are `async`: `Cache.get/put`, `RateLimiter.acquire`, `run_pipeline`. Synchronous callers can use `asyncio.run(...)`. There are no blocking fallbacks that would deadlock an async event loop.

## 9. Single source of truth for working directory

`FS.working_dir()` is the one place where the base path is resolved. All modules call `FS.run_dir(run_id)` rather than constructing paths independently. Override once via `FS.set_default_working_dir(path)` or via `bootstrap(working_dir=path)`.

## 10. Type safety

All public APIs are fully type-annotated. `from __future__ import annotations` is enabled in every file for forward-reference support. The codebase passes `mypy --strict` (with the exceptions documented in `pyproject.toml`).
