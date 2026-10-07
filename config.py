import os
from pathlib import Path


def env(name: str) -> str | None:
    """Read a setting from the process first, then the project .env file."""
    return os.environ.get(name) or _dotenv().get(name)


def use_postgres() -> bool:
    """AGENT_DB=postgres: listings, accounts and conversations all live in the group's PostgreSQL."""
    return (env("AGENT_DB") or "sqlite").strip().lower() == "postgres"


def postgres_settings() -> dict[str, str | None]:
    """Connection settings shared with the data pipeline."""
    return {
        "host": env("DB_HOST"),
        "port": env("DB_PORT"),
        "dbname": env("DB_NAME"),
        "user": env("DB_USER"),
        "password": env("DB_PASSWORD"),
        # A database that cannot be reached fails in seconds instead of hanging.
        "connect_timeout": env("DB_CONNECT_TIMEOUT") or "10",
    }


def _dotenv(path: Path | None = None) -> dict[str, str]:
    path = path or Path(__file__).with_name(".env")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}

    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
