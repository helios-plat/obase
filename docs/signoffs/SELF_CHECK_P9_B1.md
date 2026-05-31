# SELF_CHECK P9-B1 — obase.oauth2_provider

**Date:** 2026-05-31
**Status:** ✅ PASS

---

## §1 — 5 Red Lines

### pytest — 9/9 passed, coverage 100%

```
tests/test_oauth2_provider.py::test_build_authorize_url_contains_required_params PASSED
tests/test_oauth2_provider.py::test_build_authorize_url_state_is_url_encoded PASSED
tests/test_oauth2_provider.py::test_exchange_code_for_token_success PASSED
tests/test_oauth2_provider.py::test_exchange_code_for_token_oauth2_error_raises PASSED
tests/test_oauth2_provider.py::test_exchange_code_for_token_http_error_raises PASSED
tests/test_oauth2_provider.py::test_fetch_userinfo_raw_success PASSED
tests/test_oauth2_provider.py::test_fetch_userinfo_raw_no_url_raises PASSED
tests/test_oauth2_provider.py::test_fetch_userinfo_raw_http_error_raises PASSED
tests/test_oauth2_provider.py::test_oauth2_token_preserves_refresh_and_id_token PASSED
9 passed, 1 warning in 0.05s

Name                                Stmts   Miss  Cover
-------------------------------------------------------
obase/oauth2_provider/__init__.py      52      0   100%
```

### mypy --strict

```
Success: no issues found in 1 source file
```

### ruff check

```
All checks passed!
```

### git tag v0.8.0

```
v0.8.0  (pushed to github.com/helios-plat/obase)
```

### CHANGELOG

Section `## [Unreleased] → Added — obase.oauth2_provider (v0.8.0)` prepended ✓

---

## §2 — Implementation

### Module: `obase/oauth2_provider/__init__.py`

- `OAuth2ProviderConfig` — Pydantic v2 model (name, client_id, client_secret, authorize_url, token_url, userinfo_url, scope, redirect_uri)
- `OAuth2Token` — Pydantic v2 model (access_token, refresh_token, expires_in, token_type, scope, id_token)
- `build_authorize_url(config, state) → str` — urllib.parse.urlencode with response_type=code
- `exchange_code_for_token(*, config, code) → OAuth2Token` — async httpx POST x-www-form-urlencoded; OAuth2 error field → `OAuth2TokenExchangeError`; HTTP error → `OAuth2HTTPError`
- `fetch_userinfo_raw(*, config, token) → dict` — async httpx GET with Bearer; None url → `OAuth2UserInfoError`
- Exception hierarchy: `OAuth2Error` → `OAuth2TokenExchangeError`, `OAuth2UserInfoError`, `OAuth2HTTPError`

### Tests: `tests/test_oauth2_provider.py`

9 tests, all passing. `respx` not installed → used `unittest.mock.patch` + `AsyncMock` on `httpx.AsyncClient`.

---

## §3 — Deviations

- `test_fetch_userinfo_raw_http_error_raises`: raises `OAuth2HTTPError` (SPEC allowed either `OAuth2HTTPError` or `OAuth2UserInfoError`; test uses `pytest.raises((OAuth2HTTPError, OAuth2UserInfoError))`).
- No other deviations.

---

## §4 — Commits

```
4f5e3eb chore: add webhook string-payload test + uv.lock update (obase v0.8.0)
966f8fc feat(oauth2_provider): OAuth2 Authorization Code Flow — obase v0.8.0
```

Tag `v0.8.0` pushed to origin.
