# SELF_CHECK — obase B1: auth Argon2 + JWT HS256

**Date**: 2026-05-28
**Branch**: feat/c1-auth-argon2-jwt
**Files added**:
- `obase/auth/_argon2.py` — argon2_hash / argon2_verify / ArgonHashError
- `obase/auth/_jwt.py` — jwt_sign_hs256 / jwt_verify_hs256 / JWTSignError / JWTVerifyError
- `obase/auth/__init__.py` — updated exports
- `pyproject.toml` — added argon2-cffi>=23.0
- `tests/test_auth_argon2.py` — 13 tests
- `tests/test_auth_jwt_hs256.py` — 14 tests

---

## Test count

| File | Tests |
|------|-------|
| test_auth_argon2.py | 13 |
| test_auth_jwt_hs256.py | 14 |
| **Total new** | **27** |

---

## Coverage (new files only)

```
Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
obase/auth/_argon2.py      17      0   100%
obase/auth/_jwt.py         29      0   100%
-----------------------------------------------------
TOTAL                      46      0   100%
27 passed in 0.77s
```

---

## mypy --strict

```
Success: no issues found in 2 source files
```

---

## ruff

```
All checks passed!
```

---

## Regression (all existing auth tests still pass)

```
35 passed (test_auth.py + test_auth_argon2.py + test_auth_jwt_hs256.py)
```

---

## Gate summary

| Gate | Result |
|------|--------|
| Coverage ≥95% | ✓ 100% |
| Tests ≥6 per function | ✓ 13 argon2, 14 jwt |
| mypy --strict 0 errors | ✓ |
| ruff 0 errors | ✓ |
| CHANGELOG entry | ✓ |
| pyproject dep added | ✓ argon2-cffi>=23.0 |
