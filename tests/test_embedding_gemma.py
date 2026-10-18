import pytest
from unittest.mock import patch, AsyncMock

from obase.embedding_gemma import EmbeddingGemmaClient, EmbeddingGemmaError


@pytest.mark.asyncio
async def test_no_input_raises():
    c = EmbeddingGemmaClient()
    with pytest.raises(EmbeddingGemmaError):
        await c.embed()


@pytest.mark.asyncio
async def test_embed_success():
    c = EmbeddingGemmaClient()
    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.raise_for_status = lambda: None
    fake_resp.json = lambda: {"embedding": [0.1, 0.2]}
    # patch httpx
    with patch("httpx.AsyncClient") as cls:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        instance.post = AsyncMock(return_value=fake_resp)
        cls.return_value = instance
        res = await c.embed(text="hi")
        assert res == [0.1, 0.2]
