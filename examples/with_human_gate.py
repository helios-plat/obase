"""Pause + resume + resume_data human gate demo."""
from __future__ import annotations

import asyncio

from obase.exceptions import PauseRequested
from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline


async def draft_content(data: dict, ctx: OrchestratorContext) -> dict:
    return {"draft": "Here is a draft article about AI safety..."}


async def human_review_gate(data: dict, ctx: OrchestratorContext) -> dict:
    """Pause here and wait for a human to approve the draft."""
    draft = data.get("draft", "")
    print(f"[GATE] Draft ready for review:\n  {draft[:80]}")

    # In a real system, this sends a notification and the process exits.
    # On resume, resume_data contains the human's decision.
    approved = data.get("approved")
    if approved is None:
        raise PauseRequested(
            "Waiting for human approval",
            resume_data={"reviewer": "pending"},
        )
    if not approved:
        raise ValueError("Draft rejected by reviewer")
    return {"review_status": "approved", "reviewer": data.get("reviewer", "unknown")}


async def publish(data: dict, ctx: OrchestratorContext) -> dict:
    print(f"[PUBLISH] Publishing content approved by: {data.get('reviewer')}")
    return {"published": True, "url": "https://example.com/article-123"}


async def main() -> None:
    pipeline = Pipeline(
        "content-pipeline",
        [
            Stage("draft", draft_content),
            Stage("review_gate", human_review_gate),
            Stage("publish", publish),
        ],
    )

    print("=== First run: pipeline will pause at human gate ===")
    state1 = await run_pipeline(pipeline, run_id="gate-demo-1", initial_data={})
    print(f"State after first run: {state1.state}")
    print(f"Paused at: {state1.paused_at_stage}")

    # Simulate human approval — in reality this comes from a webhook/UI callback
    state1.data["approved"] = True
    state1.data["reviewer"] = "alice@example.com"

    # Write the updated data back so resume can pick it up
    import json
    from obase.fs import FS
    run_dir = FS.run_dir("gate-demo-1")
    (run_dir / "run_state.json").write_text(
        json.dumps(state1.to_dict(), default=str)
    )

    print("\n=== Second run: resume from paused stage ===")
    state2 = await run_pipeline(pipeline, run_id="gate-demo-1", resume=True)
    print(f"State after resume: {state2.state}")
    print(f"Published: {state2.data.get('published')}")
    print(f"URL: {state2.data.get('url')}")


if __name__ == "__main__":
    asyncio.run(main())
