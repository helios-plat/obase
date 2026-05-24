from typing import Protocol, runtime_checkable

from obase.exceptions import ObaseSecretsError


@runtime_checkable
class SecretsBackend(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...


_backend: SecretsBackend | None = None


def register_backend(backend: SecretsBackend) -> None:
    """Register a secrets backend."""
    global _backend
    _backend = backend


def get_secret(name: str) -> str:
    """Get a secret by name.

    Raises:
        ObaseSecretsError: If no backend is registered or secret is not found.
    """
    if _backend is None:
        raise ObaseSecretsError("No secrets backend registered")
    val = _backend.get(name)
    if val is None:
        raise ObaseSecretsError(f"Secret {name!r} not found")
    return val


def set_secret(name: str, value: str) -> None:
    """Set a secret by name.

    Raises:
        ObaseSecretsError: If no backend is registered or backend does not support set.
    """
    if _backend is None:
        raise ObaseSecretsError("No secrets backend registered")
    try:
        _backend.set(name, value)
    except NotImplementedError as e:
        raise ObaseSecretsError(str(e)) from e
    except Exception as e:
        raise ObaseSecretsError(f"Failed to set secret {name!r}: {e}") from e
