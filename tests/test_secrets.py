import base64

import pytest

from obase.exceptions import ObaseSecretsError
from obase.secrets import get_secret, load_master_key, register_backend, set_secret
from obase.secrets.backends.env_file import EnvFileBackend


def test_secrets_no_backend():
    # Reset backend for test
    import obase.secrets

    obase.secrets._backend = None
    with pytest.raises(ObaseSecretsError, match="No secrets backend registered"):
        get_secret("test")


def test_env_file_backend(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DB_PASS=secret\nAPI_KEY =  'mykey' \n# comment\nEMPTY=\n")

    backend = EnvFileBackend(str(env_file))
    register_backend(backend)

    assert get_secret("DB_PASS") == "secret"
    assert get_secret("API_KEY") == "mykey"
    assert get_secret("EMPTY") == ""

    with pytest.raises(ObaseSecretsError, match="Secret 'MISSING' not found"):
        get_secret("MISSING")


def test_env_file_backend_set():
    backend = EnvFileBackend("dummy.env")
    register_backend(backend)
    with pytest.raises(ObaseSecretsError, match="EnvFileBackend does not support set"):
        set_secret("K", "V")


def test_custom_backend():
    class MemoryBackend:
        def __init__(self):
            self.data = {}

        def get(self, name):
            return self.data.get(name)

        def set(self, name, value):
            if value == "FAIL":
                raise RuntimeError("forced failure")
            self.data[name] = value

    backend = MemoryBackend()
    register_backend(backend)

    set_secret("hello", "world")
    assert get_secret("hello") == "world"

    with pytest.raises(ObaseSecretsError, match="Failed to set secret"):
        set_secret("x", "FAIL")


def test_env_file_backend_not_found():
    backend = EnvFileBackend("nonexistent.env")
    register_backend(backend)
    with pytest.raises(ObaseSecretsError, match="Secret 'X' not found"):
        get_secret("X")


# ---------------------------------------------------------------------------
# load_master_key (#17, D2-min: env:// + file://)
# ---------------------------------------------------------------------------

_KEY = b"x" * 32


def test_load_master_key_env_base64(monkeypatch):
    monkeypatch.setenv("MK", base64.b64encode(_KEY).decode())
    assert load_master_key(source="env://MK") == _KEY


def test_load_master_key_env_hex(monkeypatch):
    monkeypatch.setenv("MK", _KEY.hex())
    assert load_master_key(source="env://MK") == _KEY


def test_load_master_key_env_missing(monkeypatch):
    monkeypatch.delenv("MK_ABSENT", raising=False)
    with pytest.raises(ObaseSecretsError, match="is not set"):
        load_master_key(source="env://MK_ABSENT")


def test_load_master_key_file_raw(tmp_path):
    p = tmp_path / "mk.bin"
    p.write_bytes(_KEY)
    assert load_master_key(source=f"file://{p}") == _KEY


def test_load_master_key_file_base64(tmp_path):
    p = tmp_path / "mk.b64"
    p.write_text(base64.b64encode(_KEY).decode() + "\n")
    assert load_master_key(source=f"file://{p}") == _KEY


def test_load_master_key_file_not_found(tmp_path):
    with pytest.raises(ObaseSecretsError, match="not found"):
        load_master_key(source=f"file://{tmp_path / 'nope'}")


def test_load_master_key_wrong_length_rejected(monkeypatch):
    monkeypatch.setenv("MK", base64.b64encode(b"short").decode())
    with pytest.raises(ObaseSecretsError, match="32 bytes"):
        load_master_key(source="env://MK")


def test_load_master_key_non_uri_rejected():
    with pytest.raises(ObaseSecretsError, match="must be a URI"):
        load_master_key(source="justastring")


def test_load_master_key_unsupported_scheme():
    with pytest.raises(ObaseSecretsError, match="unsupported"):
        load_master_key(source="age:///path/to/key")
