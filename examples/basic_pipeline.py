"""Basic pipeline: 3 stages + trail + cost + cache + rate_limit + 2 mock providers."""
from __future__ import annotations

import asyncio

from obase.bootstrap import bootstrap
from obase.cache import Cache, cached
from obase.cost_tracker import CostTracker, PricingEntry, PricingTable
from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline
from obase.provider_registry import ProviderRegistry
from obase.rate_limit import RateLimitRegistry
from obase.trail import Trail


# --- Mock providers ---

def mock_llm_provider(prompt: str) -> str:
    return f"[mock-llm] response to: {prompt}"


def mock_tts_provider(text: str) -> bytes:
    return text.encode()


# --- Pricing ---

PRICING = PricingTable(
    entries=[
        PricingEntry(category="llm", provider="mock", model_or_tier="v1", unit="token", price_usd=0.001),
        PricingEntry(category="tts", provider="mock", model_or_tier="std", unit="char", price_usd=0.00001),
    ]
)

# --- Cache ---

result_cache = Cache("basic-example", ttl_seconds=300)

# --- Rate limiter ---

RateLimitRegistry.register("mock-llm", rate=10, period_seconds=1.0)
RateLimitRegistry.register("mock-tts", rate=5, period_seconds=1.0)


# --- Stage functions ---

async def stage_generate(data: dict, ctx: OrchestratorContext) -> dict:
    """Call mock LLM, track cost, cache result."""
    rl = RateLimitRegistry.get("mock-llm")
    await rl.acquire()

    prompt = data.get("prompt", "hello world")
    cache_key = f"llm:{prompt}"
    cached_result = await result_cache.get(cache_key)
    if cached_result:
        if ctx.trail:
            ctx.trail.emit("cache_hit", stage="generate", key=cache_key)
        return {"llm_response": cached_result}

    llm = ProviderRegistry.get("llm", "mock")
    response = llm(prompt)

    if ctx.cost:
        token_count = len(response.split())
        ctx.cost.record("llm", "mock", "v1", "token", token_count)

    await result_cache.put(cache_key, response)
    return {"llm_response": response}


async def stage_tts(data: dict, ctx: OrchestratorContext) -> dict:
    """Convert text to speech with mock TTS."""
    rl = RateLimitRegistry.get("mock-tts")
    await rl.acquire()

    text = data.get("llm_response", "")
    tts = ProviderRegistry.get("tts", "mock")
    audio = tts(text)

    if ctx.cost:
        ctx.cost.record("tts", "mock", "std", "char", len(text))

    return {"audio_bytes": len(audio), "audio_preview": text[:50]}


async def stage_finalize(data: dict, ctx: OrchestratorContext) -> dict:
    """Summarize results."""
    return {"summary": f"Generated {data.get('audio_bytes', 0)} bytes of audio"}


async def main() -> None:
    bootstrap(auto_discover_providers=False)

    ProviderRegistry.register("llm", "mock", mock_llm_provider)
    ProviderRegistry.register("tts", "mock", mock_tts_provider)

    cost = CostTracker(pricing_table=PRICING, budget_usd=1.0)
    trail = Trail("basic-example-run")

    pipeline = Pipeline(
        "basic-example",
        [
            Stage("generate", stage_generate),
            Stage("tts", stage_tts),
            Stage("finalize", stage_finalize),
        ],
    )

    state = await run_pipeline(
        pipeline,
        initial_data={"prompt": "Tell me a short story about a robot"},
        trail=trail,
        cost=cost,
    )

    print(f"State: {state.state}")
    print(f"Data:  {state.data}")
    print(f"Cost:  ${cost.total_usd:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
