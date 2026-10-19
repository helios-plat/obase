"""OKX readonly broker position sync adapter (Gloomberb broker sync style).
MIT License - adapted from Gloomberb.
Helios does not place orders; this is strictly readonly position synchronization with graceful fallback.
"""
from __future__ import annotations
import httpx
from typing import Any

class OKXReadonlyBrokerAdapter:
    """Readonly broker adapter for OKX positions & account balance."""
    def __init__(self, api_key: str | None = None, api_secret: str | None = None, passphrase: str | None = None) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = "https://www.okx.com/api/v5"

    async def get_positions(self) -> dict[str, Any]:
        """Fetch readonly positions. Gracefully degrades if keys are missing or API fails."""
        if not self.api_key:
            return {
                "status": "degraded",
                "reason": "No API key provided (Helios readonly broker sync mode)",
                "positions": []
            }
        
        url = f"{self.base_url}/account/positions"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                headers = {"OK-ACCESS-KEY": self.api_key} if self.api_key else {}
                resp = await client.get(url, headers=headers)
                data = resp.json()
                return {
                    "status": "success",
                    "positions": data.get("data", [])
                }
            except Exception as e:
                return {
                    "status": "degraded",
                    "reason": str(e),
                    "positions": []
                }
