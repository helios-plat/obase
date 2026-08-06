"""obase.adaptive_scraper — scrapling-based anti-block web scraper.

Uses ``scrapling.StealthFetcher`` (TLS/JA3 fingerprint forging) to bypass
Cloudflare/WAF and extract structured content from web pages.  Falls back
to ``httpx`` when scrapling is not installed (graceful degrade).

3O element: ``obase.adaptive_scraper``.
"""

from __future__ import annotations

from typing import Any


def adaptive_scraper(
    url: str,
    selector: str | None = None,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch and parse a web page with adaptive anti-block techniques.

    Args:
        url: Target URL.
        selector: Optional CSS / XPath selector to extract content.
        context: Optional config (headers, timeout, etc.).

    Returns:
        ``{content, status, metadata, html}``
    """
    ctx = context or {}
    timeout = int(ctx.get("timeout", 30))
    headers = dict(ctx.get("headers", {}))
    try:
        from scrapling.adapters import StealthFetcher

        fetcher = StealthFetcher(
            auto_render=ctx.get("auto_render", True),
        )
        resp = fetcher.fetch(url, headers=headers, timeout=timeout)
        if resp is None:
            raise RuntimeError("scrapling returned None (blocked?)")
        html = resp.html if hasattr(resp, "html") else str(resp)
        content = html
        if selector and hasattr(resp, "select"):
            elements = resp.select(selector)
            content = "\n".join(e.text_content() for e in elements if hasattr(e, "text_content"))
    except ImportError:
        # graceful fallback: httpx with basic retry
        import httpx

        client = httpx.Client(
            timeout=timeout,
            headers={**{"User-Agent": "Veya/1.0"}, **headers},
            follow_redirects=True,
        )
        try:
            resp = client.get(url)
            html = resp.text
            content = html
            if selector:
                from lxml import html as lhtml
                tree = lhtml.fromstring(html)
                content = " ".join(tree.xpath(f"//{selector}//text()"))
        finally:
            client.close()
    except Exception as exc:
        return {"url": url, "content": "", "status": "failed", "error": str(exc)[:300], "html": ""}

    return {
        "url": url,
        "content": content[:ctx.get("max_chars", 50000)],
        "html": str(html)[:ctx.get("max_chars", 50000)] if html else "",
        "status": "fetched",
        "metadata": {
            "fetched_at": __import__("time").time(),
            "compressed": len(content) > 10000,
        },
    }
