"""Tests for obase Batch-3 submodules: crypto, migration, circuit_breaker, retry, config."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# obase.crypto
# ---------------------------------------------------------------------------
from obase.crypto.token_encryptor import CryptoError, decrypt_token, encrypt_token
from obase.crypto.key_derivation import derive_master_key


class TestCrypto:
    """obase.crypto — token_encryptor + key_derivation (≥6 tests)."""

    def _make_key(self) -> bytes:
        return os.urandom(32)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        key = self._make_key()
        plaintext = "super-secret-oauth-token"
        ct = encrypt_token(plaintext=plaintext, master_key=key)
        assert decrypt_token(ciphertext=ct, master_key=key) == plaintext

    def test_wrong_key_fails(self) -> None:
        key = self._make_key()
        ct = encrypt_token(plaintext="hello", master_key=key)
        wrong_key = self._make_key()
        with pytest.raises(CryptoError):
            decrypt_token(ciphertext=ct, master_key=wrong_key)

    def test_ciphertext_does_not_contain_plaintext(self) -> None:
        key = self._make_key()
        plaintext = "my-secret-token-abc123"
        ct = encrypt_token(plaintext=plaintext, master_key=key)
        assert plaintext.encode() not in ct.encode()
        assert plaintext not in ct

    def test_derive_same_password_and_salt_gives_same_key(self) -> None:
        salt = os.urandom(16)
        key1, s1 = derive_master_key(password="password", salt=salt, memory_cost=8192, time_cost=1)
        key2, s2 = derive_master_key(password="password", salt=salt, memory_cost=8192, time_cost=1)
        assert key1 == key2
        assert s1 == s2 == salt

    def test_derive_no_salt_generates_different_salts(self) -> None:
        key1, salt1 = derive_master_key(password="pw", memory_cost=8192, time_cost=1)
        key2, salt2 = derive_master_key(password="pw", memory_cost=8192, time_cost=1)
        assert salt1 != salt2
        assert key1 != key2

    def test_wrong_key_length_raises_crypto_error(self) -> None:
        short_key = b"tooshort"
        with pytest.raises(CryptoError, match="32 bytes"):
            encrypt_token(plaintext="x", master_key=short_key)
        with pytest.raises(CryptoError, match="32 bytes"):
            decrypt_token(ciphertext="abc", master_key=short_key)

    def test_derive_wrong_salt_length_raises(self) -> None:
        with pytest.raises(CryptoError, match="16 bytes"):
            derive_master_key(password="pw", salt=b"tooshort", memory_cost=8192, time_cost=1)

    def test_encrypt_decrypt_unicode_payload(self) -> None:
        key = self._make_key()
        plaintext = "你好世界 — тест — émoji 🔑"
        ct = encrypt_token(plaintext=plaintext, master_key=key)
        assert decrypt_token(ciphertext=ct, master_key=key) == plaintext


# ---------------------------------------------------------------------------
# obase.migration
# ---------------------------------------------------------------------------
from obase.migration import MigrationResult, run_migration


class TestMigration:
    """obase.migration — run_migration (≥3 tests)."""

    def test_unknown_action_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown migration action"):
            run_migration(
                dsn="postgresql://localhost/test", migrations_path=tmp_path, action="nope"
            )

    def test_mock_alembic_upgrade_success(self, tmp_path: Path) -> None:
        with (
            patch("obase.migration.command") as mock_cmd,
            patch("obase.migration.create_engine") as mock_engine,
        ):
            # Set up mock engine / connection / MigrationContext
            mock_conn = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.get_current_revision.return_value = "abc123"
            mock_engine.return_value.__enter__ = MagicMock(return_value=mock_engine.return_value)
            mock_engine.return_value.connect.return_value.__enter__ = MagicMock(
                return_value=mock_conn
            )
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

            with patch("obase.migration.MigrationContext") as mock_mc:
                mock_mc.configure.return_value = mock_ctx

                result = run_migration(
                    dsn="postgresql://localhost/test",
                    migrations_path=tmp_path,
                    action="upgrade",
                    target="head",
                )

            mock_cmd.upgrade.assert_called_once()
            assert result.action == "upgrade"
            assert result.success is True

    def test_mock_engine_current_revision(self, tmp_path: Path) -> None:
        with (
            patch("obase.migration.command"),
            patch("obase.migration.create_engine") as mock_engine,
            patch("obase.migration.MigrationContext") as mock_mc,
        ):
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__ = MagicMock(
                return_value=mock_conn
            )
            mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_ctx = MagicMock()
            mock_ctx.get_current_revision.return_value = "rev_xyz"
            mock_mc.configure.return_value = mock_ctx

            result = run_migration(
                dsn="postgresql://localhost/test",
                migrations_path=tmp_path,
                action="current",
            )

            assert result.success is True
            assert result.current_revision == "rev_xyz"

    def test_migration_failure_returns_error_result(self, tmp_path: Path) -> None:
        with patch("obase.migration.command") as mock_cmd:
            mock_cmd.upgrade.side_effect = RuntimeError("DB connection refused")
            result = run_migration(
                dsn="postgresql://localhost/test",
                migrations_path=tmp_path,
                action="upgrade",
            )
        assert result.success is False
        assert result.error is not None
        assert "DB connection refused" in result.error


# ---------------------------------------------------------------------------
# obase.circuit_breaker
# ---------------------------------------------------------------------------
from obase.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class TestCircuitBreaker:
    """obase.circuit_breaker — CircuitBreaker (≥7 tests)."""

    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        assert cb.state == "closed"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_three_failures_opens_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        async def bad() -> None:
            raise ConnectionError("boom")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(bad)

        assert cb.state == "open"
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_rejects_immediately(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)

        async def bad() -> None:
            raise ConnectionError("boom")

        with pytest.raises(ConnectionError):
            await cb.call(bad)

        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(bad)

    def test_reset_returns_to_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30.0)
        # Manually set open state
        cb._state = "open"  # type: ignore[attr-defined]
        cb._failure_count = 5  # type: ignore[attr-defined]
        cb.reset()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        async def bad() -> None:
            raise ConnectionError("boom")

        with pytest.raises(ConnectionError):
            await cb.call(bad)

        assert cb.state == "open"

        # Wait for recovery timeout
        await asyncio.sleep(0.02)
        assert cb.state == "half_open"

        async def good() -> str:
            return "ok"

        result = await cb.call(good)
        assert result == "ok"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_concurrent_safety(self) -> None:
        """Multiple concurrent failures should not corrupt state."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

        async def bad() -> None:
            raise ConnectionError("boom")

        tasks = [asyncio.create_task(cb.call(bad)) for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(r, (ConnectionError, CircuitBreakerOpenError)) for r in results)
        assert cb.state == "open"

    @pytest.mark.asyncio
    async def test_sync_func_works(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

        def sync_ok() -> int:
            return 42

        result = await cb.call(sync_ok)
        assert result == 42
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        async def bad() -> None:
            raise ConnectionError("boom")

        with pytest.raises(ConnectionError):
            await cb.call(bad)

        await asyncio.sleep(0.02)
        assert cb.state == "half_open"

        # Failure in half_open should reopen
        with pytest.raises(ConnectionError):
            await cb.call(bad)

        assert cb.state == "open"


# ---------------------------------------------------------------------------
# obase.retry
# ---------------------------------------------------------------------------
from obase.retry import RetryPolicy


class TestRetryPolicy:
    """obase.retry — RetryPolicy (≥6 tests)."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.0)
        call_count = 0

        async def ok() -> str:
            nonlocal call_count
            call_count += 1
            return "done"

        result = await policy.execute(ok)
        assert result == "done"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.0)
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("not yet")
            return "ok"

        result = await policy.execute(flaky)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausted_raises_last_exception(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.0)

        async def always_bad() -> None:
            raise ConnectionError("always")

        with pytest.raises(ConnectionError, match="always"):
            await policy.execute(always_bad)

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self) -> None:
        policy = RetryPolicy(max_retries=3, base_delay=0.0)
        call_count = 0

        async def bad() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await policy.execute(bad)

        assert call_count == 1  # Not retried

    @pytest.mark.asyncio
    async def test_max_delay_capped(self) -> None:
        """Verify delay is capped at max_delay (mock asyncio.sleep)."""
        policy = RetryPolicy(
            max_retries=3,
            base_delay=100.0,
            max_delay=5.0,
            backoff_factor=2.0,
        )
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        async def always_bad() -> None:
            raise ConnectionError("x")

        with patch("obase.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(ConnectionError):
                await policy.execute(always_bad)

        assert all(d <= 5.0 for d in sleep_calls)
        assert len(sleep_calls) == 3  # 3 retries = 3 sleeps

    @pytest.mark.asyncio
    async def test_sync_func_works(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.0)
        call_count = 0

        def sync_ok() -> int:
            nonlocal call_count
            call_count += 1
            return 99

        result = await policy.execute(sync_ok)
        assert result == 99
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self) -> None:
        policy = RetryPolicy(
            max_retries=2,
            base_delay=0.0,
            retryable_exceptions=(ValueError,),
        )
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry me")
            return "done"

        result = await policy.execute(flaky)
        assert result == "done"
        assert call_count == 3


# ---------------------------------------------------------------------------
# obase.config
# ---------------------------------------------------------------------------
from obase.config import load_config, watch_config
from pydantic import BaseModel as PydanticBaseModel


class _AppSchema(PydanticBaseModel):
    host: str
    port: int


class TestConfig:
    """obase.config — load_config + watch_config (≥5 tests)."""

    def test_single_file(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("host: localhost\nport: 8080\n")
        result = load_config(paths=[cfg_file], env_prefix="NONEXISTENT_PREFIX_XYZ_")
        assert result["host"] == "localhost"
        assert result["port"] == 8080

    def test_multiple_files_deep_merge(self, tmp_path: Path) -> None:
        base = tmp_path / "base.yaml"
        base.write_text("db:\n  host: localhost\n  port: 5432\napp: base\n")
        override = tmp_path / "override.yaml"
        override.write_text("db:\n  port: 9999\napp: override\n")
        result = load_config(paths=[base, override], env_prefix="NONEXISTENT_PREFIX_XYZ_")
        assert result["db"]["host"] == "localhost"  # preserved from base
        assert result["db"]["port"] == 9999  # overridden
        assert result["app"] == "override"

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        real = tmp_path / "real.yaml"
        real.write_text("key: value\n")
        missing = tmp_path / "nonexistent.yaml"
        result = load_config(paths=[missing, real], env_prefix="NONEXISTENT_PREFIX_XYZ_")
        assert result["key"] == "value"

    def test_env_override_applied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("host: localhost\n")
        monkeypatch.setenv("TESTPREFIX_HOST", "remotehost")
        result = load_config(paths=[cfg_file], env_prefix="TESTPREFIX_")
        assert result["host"] == "remotehost"

    def test_schema_validation_failure(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("host: localhost\nport: not_a_number\n")
        with pytest.raises(ValueError, match="Config validation failed"):
            load_config(
                paths=[cfg_file],
                schema=_AppSchema,
                env_prefix="NONEXISTENT_PREFIX_XYZ_",
            )

    def test_schema_validation_success(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("host: myhost\nport: 3000\n")
        result = load_config(
            paths=[cfg_file],
            schema=_AppSchema,
            env_prefix="NONEXISTENT_PREFIX_XYZ_",
        )
        assert result["host"] == "myhost"
        assert result["port"] == 3000

    def test_watch_config_calls_callback_on_change(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("key: initial\n")

        received: list[dict] = []

        handle = watch_config(
            paths=[cfg_file],
            callback=received.append,
            interval=0.05,
            env_prefix="NONEXISTENT_PREFIX_XYZ_",
        )

        import time

        time.sleep(0.1)
        cfg_file.write_text("key: updated\n")
        time.sleep(0.2)
        handle.stop()

        # At least one callback should have been triggered by the file change
        assert any(c.get("key") == "updated" for c in received)
