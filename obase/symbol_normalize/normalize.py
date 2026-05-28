"""Symbol normalization — canonical form conversion and validation."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CANONICAL_PATTERN = r"^[A-Z0-9]{1,10}(-[A-Z0-9]{1,10}){0,5}$"
CANONICAL_REGEX = re.compile(CANONICAL_PATTERN)
MAX_LENGTH = 64

KNOWN_QUOTES = (
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "TRY",
    "BTC",
    "ETH",
    "BNB",
)

COINGECKO_SLUG_TO_ASSET = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
}
COINGECKO_ASSET_TO_SLUG = {v: k for k, v in COINGECKO_SLUG_TO_ASSET.items()}

_DERIBIT_MONTHS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}

SourceLiteral = Literal[
    "binance",
    "binance_futures",
    "okx_spot",
    "okx_swap",
    "yfinance",
    "helixa",
    "coingecko",
    "deribit",
]


class Instrument(str, Enum):  # noqa: UP042
    """Instrument type enumeration."""

    SPOT = "spot"
    PERP = "perp"
    FUT = "futures"
    CALL = "option_call"
    PUT = "option_put"
    ASSET = "asset"


class SymbolNormalizeError(ValueError):
    """Raised when symbol cannot be normalized to canonical form."""


def to_canonical(
    raw: str,
    source: SourceLiteral | None = None,
    instrument: Instrument | None = None,
) -> str:
    """Convert any source's symbol format to canonical form.

    Args:
        raw: Raw symbol string in any known format.
        source: Data source identifier. None means passthrough (must be canonical).
        instrument: Explicit instrument type (for disambiguation).

    Returns:
        Canonical form symbol.

    Raises:
        SymbolNormalizeError: On unknown source, unrecognized format, or validation failure.

    Example:
        >>> to_canonical("BTCUSDT", source="binance")
        'BTC-USDT'
    """
    if not isinstance(raw, str) or not raw.strip():
        raise SymbolNormalizeError(f"Empty or non-string input: {raw!r}")

    s = raw.strip()

    if source == "binance":
        result = _normalize_binance_concat(s.upper(), instrument=instrument)
    elif source == "binance_futures":
        result = _normalize_binance_concat(s.upper(), instrument=Instrument.PERP)
    elif source == "okx_spot":
        result = _normalize_okx_spot(s.upper())
    elif source == "okx_swap":
        result = _normalize_okx_swap(s.upper())
    elif source == "helixa":
        result = _normalize_okx_spot(s.upper())
    elif source == "yfinance":
        result = _normalize_yfinance(s.upper())
    elif source == "coingecko":
        result = _normalize_coingecko_slug(s)
    elif source == "deribit":
        result = _normalize_deribit(s.upper())
    elif source is None:
        result = _strip_spot_suffix(s.upper())
    else:
        raise SymbolNormalizeError(f"Unknown source: {source!r}")

    _validate_canonical(result, original=raw)
    return result


def to_binance_concat(canonical: str) -> str:
    """Canonical → binance concat (BTC-USDT → BTCUSDT).

    Args:
        canonical: Canonical form symbol (spot or perp only).

    Returns:
        Binance concatenated format.

    Raises:
        SymbolNormalizeError: If instrument is not spot/perp.

    Example:
        >>> to_binance_concat("BTC-USDT")
        'BTCUSDT'
    """
    components = parse_components(canonical)
    inst = components["instrument"]
    if inst not in (Instrument.SPOT, Instrument.PERP):
        raise SymbolNormalizeError(f"to_binance_concat supports spot/perp only, got {canonical!r}")
    return f"{components['base']}{components['quote']}"


def to_helixa_format(canonical: str) -> str:
    """Canonical → helixa/ccxt format (BTC-USDT → BTC/USDT).

    Args:
        canonical: Canonical form symbol.

    Returns:
        Slash-separated format (perp adds :QUOTE suffix).

    Raises:
        SymbolNormalizeError: If instrument is not spot/perp.

    Example:
        >>> to_helixa_format("BTC-USDT")
        'BTC/USDT'
    """
    components = parse_components(canonical)
    inst = components["instrument"]
    base = components["base"]
    quote = components["quote"]
    if inst == Instrument.SPOT:
        return f"{base}/{quote}"
    if inst == Instrument.PERP:
        return f"{base}/{quote}:{quote}"
    raise SymbolNormalizeError(f"to_helixa_format supports spot/perp only, got {canonical!r}")


def to_okx_format(canonical: str) -> str:
    """Canonical → OKX format (alias of to_helixa_format).

    Args:
        canonical: Canonical form symbol.

    Returns:
        OKX/ccxt format string.

    Raises:
        SymbolNormalizeError: If instrument is not spot/perp.

    Example:
        >>> to_okx_format("BTC-USDT-PERP")
        'BTC/USDT:USDT'
    """
    return to_helixa_format(canonical)


def to_coingecko_slug(canonical: str) -> str:
    """Canonical asset → coingecko slug (BTC → bitcoin).

    Args:
        canonical: Canonical form symbol.

    Returns:
        CoinGecko slug string.

    Raises:
        SymbolNormalizeError: If no mapping exists for the asset.

    Example:
        >>> to_coingecko_slug("BTC")
        'bitcoin'
    """
    components = parse_components(canonical)
    asset = components["base"]
    slug = COINGECKO_ASSET_TO_SLUG.get(asset)
    if not slug:
        raise SymbolNormalizeError(f"No coingecko slug mapping for asset: {asset!r}")
    return slug


def from_coingecko_slug(slug: str) -> str:
    """CoinGecko slug → asset-only canonical (bitcoin → BTC).

    Args:
        slug: CoinGecko slug string.

    Returns:
        Asset-only canonical form.

    Raises:
        SymbolNormalizeError: If slug is unknown.

    Example:
        >>> from_coingecko_slug("bitcoin")
        'BTC'
    """
    return _normalize_coingecko_slug(slug)


def is_canonical(symbol: str) -> bool:
    """Check if symbol is in canonical form.

    Args:
        symbol: Symbol string to validate.

    Returns:
        True if valid canonical form, False otherwise.

    Example:
        >>> is_canonical("BTC-USDT")
        True
    """
    if not isinstance(symbol, str):
        return False
    if len(symbol) > MAX_LENGTH:
        return False
    if symbol.endswith("-SPOT"):
        return False
    return bool(CANONICAL_REGEX.match(symbol))


def parse_components(canonical: str) -> dict:
    """Parse canonical form into structured fields.

    Args:
        canonical: Canonical form symbol string.

    Returns:
        Dict with keys: base, quote, instrument, strike, expiration.

    Raises:
        SymbolNormalizeError: If not valid canonical form.

    Example:
        >>> parse_components("BTC-USDT-PERP")
        {'base': 'BTC', 'quote': 'USDT', 'instrument': <Instrument.PERP>, ...}
    """
    if not is_canonical(canonical):
        raise SymbolNormalizeError(f"Not canonical form: {canonical!r}")

    parts = canonical.split("-")

    if len(parts) == 1:
        return {
            "base": parts[0],
            "quote": None,
            "instrument": Instrument.ASSET,
            "strike": None,
            "expiration": None,
        }
    if len(parts) == 2:
        return {
            "base": parts[0],
            "quote": parts[1],
            "instrument": Instrument.SPOT,
            "strike": None,
            "expiration": None,
        }
    if len(parts) == 3 and parts[2] == "PERP":
        return {
            "base": parts[0],
            "quote": parts[1],
            "instrument": Instrument.PERP,
            "strike": None,
            "expiration": None,
        }
    if len(parts) == 4 and parts[2] == "FUT":
        return {
            "base": parts[0],
            "quote": parts[1],
            "instrument": Instrument.FUT,
            "strike": None,
            "expiration": parts[3],
        }
    if len(parts) == 5 and parts[2] in ("CALL", "PUT"):
        instrument = Instrument.CALL if parts[2] == "CALL" else Instrument.PUT
        try:
            strike = int(parts[3])
        except ValueError as e:
            raise SymbolNormalizeError(
                f"Invalid option strike in {canonical!r}: {parts[3]!r}"
            ) from e
        return {
            "base": parts[0],
            "quote": parts[1],
            "instrument": instrument,
            "strike": strike,
            "expiration": parts[4],
        }

    raise SymbolNormalizeError(f"Cannot parse components from {canonical!r}")


class SymbolModel(BaseModel):
    """Canonical Symbol pydantic model for validation.

    Example:
        >>> m = SymbolModel(raw="BTC-USDT")
        >>> m.components
        {'base': 'BTC', ...}
    """

    raw: str = Field(..., max_length=MAX_LENGTH, pattern=CANONICAL_PATTERN)

    @field_validator("raw")
    @classmethod
    def must_be_canonical(cls, v: str) -> str:
        """Validate canonical form (rejects -SPOT suffix)."""
        if v.endswith("-SPOT"):
            raise ValueError("SPOT suffix forbidden, use base form")
        return v

    @property
    def components(self) -> dict:
        """Parse into structured components."""
        return parse_components(self.raw)


# ── Private helpers ──────────────────────────────────────────────────────────


def _normalize_binance_concat(s: str, instrument: Instrument | None = None) -> str:
    for quote in KNOWN_QUOTES:
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            if 1 <= len(base) <= 10:
                canonical = f"{base}-{quote}"
                if instrument == Instrument.PERP:
                    canonical += "-PERP"
                return canonical
    raise SymbolNormalizeError(f"Cannot split binance concat {s!r}: no known quote suffix")


def _normalize_okx_spot(s: str) -> str:
    if "/" in s:
        return s.replace("/", "-")
    return _strip_spot_suffix(s)


def _normalize_okx_swap(s: str) -> str:
    if ":" not in s:
        raise SymbolNormalizeError(f"okx_swap symbol must contain ':' suffix, got {s!r}")
    base_quote, _settle = s.split(":", 1)
    if "/" not in base_quote:
        raise SymbolNormalizeError(f"okx_swap base/quote part malformed: {s!r}")
    return base_quote.replace("/", "-") + "-PERP"


def _normalize_yfinance(s: str) -> str:
    s = _strip_spot_suffix(s)
    if "." in s or "^" in s or "=" in s:
        raise SymbolNormalizeError(f"yfinance non-crypto ticker not supported: {s!r}")
    return s


def _normalize_coingecko_slug(s: str) -> str:
    asset = COINGECKO_SLUG_TO_ASSET.get(s.strip().lower())
    if not asset:
        raise SymbolNormalizeError(f"Unknown coingecko slug: {s!r}")
    return asset


def _normalize_deribit(s: str) -> str:
    parts = s.split("-")
    asset = parts[0]
    if len(parts) == 2 and parts[1] == "PERPETUAL":
        return f"{asset}-USD-PERP"
    if len(parts) == 2:
        expiration = _parse_deribit_date(parts[1])
        return f"{asset}-USD-FUT-{expiration}"
    if len(parts) == 4 and parts[3] in ("C", "P"):
        expiration = _parse_deribit_date(parts[1])
        strike = parts[2]
        side = "CALL" if parts[3] == "C" else "PUT"
        return f"{asset}-USD-{side}-{strike}-{expiration}"
    raise SymbolNormalizeError(f"Unknown deribit instrument format: {s!r}")


def _parse_deribit_date(token: str) -> str:
    m = re.fullmatch(r"(\d{1,2})([A-Z]{3})(\d{2})", token)
    if not m:
        raise SymbolNormalizeError(f"Invalid deribit date token: {token!r}")
    day, mon_abbr, yy = m.groups()
    mm = _DERIBIT_MONTHS.get(mon_abbr)
    if not mm:
        raise SymbolNormalizeError(f"Unknown deribit month abbreviation: {mon_abbr!r}")
    return f"{yy}{mm}{day.zfill(2)}"


def _strip_spot_suffix(s: str) -> str:
    if s.endswith("-SPOT"):
        return s[:-5]
    return s


def _validate_canonical(s: str, original: str) -> None:
    if len(s) > MAX_LENGTH:
        raise SymbolNormalizeError(
            f"Symbol exceeds max length {MAX_LENGTH}: {s!r} (from {original!r})"
        )
    if not CANONICAL_REGEX.match(s):
        raise SymbolNormalizeError(f"Result {s!r} is not canonical form (from {original!r})")
