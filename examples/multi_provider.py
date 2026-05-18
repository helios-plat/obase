"""Runtime provider switching demo."""
from __future__ import annotations

import asyncio

from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline
from obase.provider_registry import ProviderRegistry


# --- Two mock LLM providers ---

def openai_mock(prompt: str) -> str:
    return f"[openai] {prompt}"


def anthropic_mock(prompt: str) -> str:
    return f"[anthropic] {prompt}"


# --- Stage that reads provider name from pipeline data ---

async def call_llm(data: dict, ctx: OrchestratorContext) -> dict:
    provider_name = data.get("llm_provider", "openai")
    llm = ProviderRegistry.get("llm", provider_name)
    response = llm(data.get("prompt", "hello"))
    return {"response": response, "used_provider": provider_name}


async def run_with_provider(provider: str) -> None:
    pipeline = Pipeline("multi-provider", [Stage("llm", call_llm)])
    state = await run_pipeline(
        pipeline,
        initial_data={"prompt": "What is 2+2?", "llm_provider": provider},
    )
    print(f"Provider={provider!r}: {state.data['response']}")


async def main() -> None:
    ProviderRegistry.register("llm", "openai", openai_mock)
    ProviderRegistry.register("llm", "anthropic", anthropic_mock)

    print("=== Running with different providers ===")
    await run_with_provider("openai")
    await run_with_provider("anthropic")

    print("\n=== Hot-swapping provider at runtime ===")
    def fast_mock(prompt: str) -> str:
        return f"[fast-mock] {prompt}"

    ProviderRegistry.register("llm", "fast", fast_mock)
    await run_with_provider("fast")

    print("\n=== Available providers ===")
    for cat, name in ProviderRegistry.list_providers():
        print(f"  {cat}/{name}")


if __name__ == "__main__":
    asyncio.run(main())
