import os
from pathlib import Path


def env(name: str) -> str | None:
    """Read a setting from the process first, then the project .env file."""
    return os.environ.get(name) or _dotenv().get(name)


DB_SETTINGS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def missing_db_settings() -> str | None:
    """What to fix when a DB_* setting is not set, else None. Each one is needed: without DB_USER,
    for one, PostgreSQL's client quietly uses the computer's user name and the server answers with a
    puzzling authentication error."""
    missing = [name for name in DB_SETTINGS if not env(name)]
    if not missing:
        return None
    names = missing[0] if len(missing) == 1 else f"{', '.join(missing[:-1])} and {missing[-1]}"
    return f".env is missing {names}. Add {'it' if len(missing) == 1 else 'them'} and run again (see .env.example)."


def postgres_settings() -> dict[str, str | None]:
    """Connection settings for the project's PostgreSQL, shared with the data pipeline."""
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
