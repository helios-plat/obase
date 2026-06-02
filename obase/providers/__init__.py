"""obase default provider registrations.

Call ``register_default_providers()`` once at application startup to populate
ProviderRegistry with all built-in providers that have their dependencies and
secrets available.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def register_default_providers(*, replace: bool = False) -> None:
    """Register all built-in providers into ProviderRegistry.

    Each provider is registered only if its optional dependency is installed
    (for edge_tts) or its required secret is present (for wanxiang). Missing
    deps/secrets are silently skipped — no ImportError or SecretsError raised.

    Args:
        replace: Pass True to overwrite already-registered providers.
    """
    # TTS — edge-tts (optional dep: edge-tts>=6.1)
    try:
        from obase.providers._tts.edge_tts import register as _reg_edge_tts

        _reg_edge_tts(replace=replace)
        log.info("obase.providers.registered", provider="edge_tts")
    except ImportError:
        log.debug("obase.providers.skipped", provider="edge_tts", reason="edge-tts not installed")

    # Image generation — DashScope wanxiang (requires DASHSCOPE_API_KEY)
    from obase.providers._image.dashscope_wanxiang import register as _reg_wanxiang

    _reg_wanxiang(replace=replace)
    # wanxiang's register() logs nothing on skip; log only if registered
    from obase.provider_registry import ProviderRegistry

    if ProviderRegistry.has("image_gen", "wanxiang"):
        log.info("obase.providers.registered", provider="wanxiang")
