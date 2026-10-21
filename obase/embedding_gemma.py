"""obase.embedding_gemma — EmbeddingGemma client + multimodal adapter (lazy)."""

from __future__ import annotations

from typing import Any


class EmbeddingGemmaError(RuntimeError):
    pass


class EmbeddingGemmaClient:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "embeddinggemma",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def embed(
        self,
        *,
        text: str | None = None,
        image_path: str | None = None,
        code: str | None = None,
    ) -> list[float]:
        import httpx
        payload: dict[str, Any] = {"model": self.model}
        if text is not None:
            payload["input"] = text
        elif code is not None:
            payload["input"] = code
        elif image_path is not None:
            payload["input"] = image_path
        else:
            raise EmbeddingGemmaError("one of text/image_path/code required")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{self.base_url}/api/embeddings", json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            raise EmbeddingGemmaError(f"embedding request failed: {exc}") from exc
        emb = data.get("embedding") or data.get("embeddings")
        if isinstance(emb, list) and emb and isinstance(emb[0], list):
            emb = emb[0]
        if not isinstance(emb, list):
            raise EmbeddingGemmaError("no embedding in response")
        return [float(x) for x in emb]


def get_embedding_gemma_client(**kw: Any) -> EmbeddingGemmaClient:
    return EmbeddingGemmaClient(**kw)
