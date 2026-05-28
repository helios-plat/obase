"""Tests for obase.symbol_normalize."""

from __future__ import annotations

import pytest

from obase.symbol_normalize import (
    Instrument,
    SymbolModel,
    SymbolNormalizeError,
    from_coingecko_slug,
    is_canonical,
    parse_components,
    to_binance_concat,
    to_canonical,
    to_coingecko_slug,
    to_helixa_format,
    to_okx_format,
)


class TestToCanonical:
    def test_binance_spot(self):
        assert to_canonical("BTCUSDT", source="binance") == "BTC-USDT"

    def test_binance_futures(self):
        assert to_canonical("ETHUSDT", source="binance_futures") == "ETH-USDT-PERP"

    def test_okx_spot(self):
        assert to_canonical("BTC/USDT", source="okx_spot") == "BTC-USDT"

    def test_okx_swap(self):
        assert to_canonical("BTC/USDT:USDT", source="okx_swap") == "BTC-USDT-PERP"

    def test_coingecko(self):
        assert to_canonical("bitcoin", source="coingecko") == "BTC"

    def test_deribit_perpetual(self):
        assert to_canonical("BTC-PERPETUAL", source="deribit") == "BTC-USD-PERP"

    def test_deribit_option_call(self):
        result = to_canonical("BTC-25DEC25-50000-C", source="deribit")
        assert result == "BTC-USD-CALL-50000-251225"

    def test_passthrough_canonical(self):
        assert to_canonical("BTC-USDT") == "BTC-USDT"

    def test_empty_raises(self):
        with pytest.raises(SymbolNormalizeError):
            to_canonical("")

    def test_unknown_source_raises(self):
        with pytest.raises(SymbolNormalizeError):
            to_canonical("BTC", source="unknown")  # type: ignore


class TestReverseFunctions:
    def test_to_binance_concat(self):
        assert to_binance_concat("BTC-USDT") == "BTCUSDT"

    def test_to_binance_concat_perp(self):
        assert to_binance_concat("BTC-USDT-PERP") == "BTCUSDT"

    def test_to_helixa_spot(self):
        assert to_helixa_format("BTC-USDT") == "BTC/USDT"

    def test_to_helixa_perp(self):
        assert to_helixa_format("BTC-USDT-PERP") == "BTC/USDT:USDT"

    def test_to_okx_format_alias(self):
        assert to_okx_format("ETH-USDT") == "ETH/USDT"

    def test_to_coingecko_slug(self):
        assert to_coingecko_slug("BTC") == "bitcoin"

    def test_from_coingecko_slug(self):
        assert from_coingecko_slug("ethereum") == "ETH"

    def test_to_coingecko_unknown_raises(self):
        with pytest.raises(SymbolNormalizeError):
            to_coingecko_slug("UNKNOWN-COIN")


class TestValidation:
    def test_is_canonical_valid(self):
        assert is_canonical("BTC-USDT") is True

    def test_is_canonical_spot_suffix_rejected(self):
        assert is_canonical("BTC-USDT-SPOT") is False

    def test_is_canonical_too_long(self):
        assert is_canonical("A" * 65) is False

    def test_is_canonical_non_string(self):
        assert is_canonical(123) is False  # type: ignore


class TestParseComponents:
    def test_asset_only(self):
        c = parse_components("BTC")
        assert c["base"] == "BTC"
        assert c["instrument"] == Instrument.ASSET

    def test_spot(self):
        c = parse_components("BTC-USDT")
        assert c["instrument"] == Instrument.SPOT
        assert c["quote"] == "USDT"

    def test_perp(self):
        c = parse_components("BTC-USDT-PERP")
        assert c["instrument"] == Instrument.PERP

    def test_futures(self):
        c = parse_components("BTC-USDT-FUT-20251225")
        assert c["instrument"] == Instrument.FUT
        assert c["expiration"] == "20251225"

    def test_option(self):
        c = parse_components("BTC-USD-CALL-50000-251225")
        assert c["instrument"] == Instrument.CALL
        assert c["strike"] == 50000

    def test_invalid_raises(self):
        with pytest.raises(SymbolNormalizeError):
            parse_components("not canonical!")


class TestSymbolModel:
    def test_valid(self):
        m = SymbolModel(raw="BTC-USDT")
        assert m.components["base"] == "BTC"

    def test_spot_suffix_rejected(self):
        with pytest.raises(ValueError):
            SymbolModel(raw="BTC-USDT-SPOT")

    def test_invalid_pattern(self):
        with pytest.raises(ValueError):
            SymbolModel(raw="btc_usdt")
