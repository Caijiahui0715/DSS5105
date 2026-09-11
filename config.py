import os
from pathlib import Path


def env(name: str) -> str | None:
    """Read a setting from the process first, then the project .env file."""
    return os.environ.get(name) or _dotenv().get(name)


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
