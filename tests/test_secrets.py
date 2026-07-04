
import pytest

from obase.exceptions import ObaseSecretsError
from obase.secrets import get_secret, register_backend, set_secret
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
