import os


class EnvFileBackend:
    """Read secrets from a .env file. set() is not implemented."""

    def __init__(self, env_path: str):
        self.env_path = env_path
        self._secrets: dict[str, str] = {}
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        # Remove potential quotes
                        val = val.strip()
                        if (val.startswith('"') and val.endswith('"')) or (
                            val.startswith("'") and val.endswith("'")
                        ):
                            val = val[1:-1]
                        self._secrets[key.strip()] = val

    def get(self, name: str) -> str | None:
        """Get secret from loaded env data."""
        return self._secrets.get(name)

    def set(self, name: str, value: str) -> None:
        """Set is not supported by EnvFileBackend."""
        raise NotImplementedError("EnvFileBackend does not support set()")
