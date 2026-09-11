import base64
import json
import os
from math import ceil
from pathlib import Path
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import env


_BASE_URL = "https://www.onemap.gov.sg"
_TOKEN_PATH = "/api/auth/post/getToken"
_TOKEN_CACHE = Path(__file__).with_name(".onemap_token.json")
_RENEW_MARGIN_SECONDS = 300


class OneMapError(RuntimeError):
    pass


class OneMapNotFound(OneMapError):
    """The API answered normally but had no match for the query."""


def get_token(
    email: str | None = None,
    password: str | None = None,
    *,
    opener=urlopen,
) -> dict[str, object]:
    """POST OneMap credentials and return a fresh access token with its expiry.

    Credentials default to ONEMAP_EMAIL / ONEMAP_PASSWORD, read from the
    environment first and from the project .env as a fallback. They are never
    logged or included in raised errors.
    """
    email = email or env("ONEMAP_EMAIL")
    password = password or env("ONEMAP_PASSWORD")
    if not email or not password:
        raise OneMapError("ONEMAP_EMAIL and ONEMAP_PASSWORD are required")

    request = Request(
        f"{_BASE_URL}{_TOKEN_PATH}",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise OneMapError(f"OneMap refused the token request (HTTP {error.code})") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise OneMapError("OneMap token request failed") from error

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise OneMapError("OneMap returned no access_token")

    return {
        "access_token": token,
        "expiry_timestamp": int(payload.get("expiry_timestamp") or 0),
    }


def load_token(*, cache_path: Path = _TOKEN_CACHE, opener=urlopen, refresh: bool = False) -> str:
    """Return a usable token, reusing the cached one until it is about to expire.

    OneMap tokens last three days and do not auto-renew, so callers should use
    this instead of pasting a token into .env by hand.
    """
    if not refresh:
        supplied = env("ONEMAP_TOKEN")
        if supplied and not _is_expired(supplied):
            return supplied
        cached = _read_cached_token(cache_path)
        if cached:
            return cached

    fresh = get_token(opener=opener)
    _write_cached_token(cache_path, fresh)
    return str(fresh["access_token"])


def token_expiry(token: str) -> int | None:
    """Read the exp claim out of a OneMap JWT without calling the network."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        segment = parts[1]
        padded = segment + "=" * (-len(segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    expiry = claims.get("exp")
    return int(expiry) if isinstance(expiry, (int, float, str)) and str(expiry).isdigit() else None


def _is_expired(token: str) -> bool:
    expiry = token_expiry(token)
    return expiry is not None and expiry - _RENEW_MARGIN_SECONDS <= time()


def _read_cached_token(cache_path: Path) -> str | None:
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    token = cached.get("access_token")
    expiry = cached.get("expiry_timestamp") or 0
    if token and int(expiry) - _RENEW_MARGIN_SECONDS > time():
        return str(token)
    return None


def _write_cached_token(cache_path: Path, token: dict[str, object]) -> None:
    try:
        cache_path.write_text(json.dumps(token), encoding="utf-8")
        os.chmod(cache_path, 0o600)
    except OSError:
        pass  # A cache miss is recoverable; a failed write must not break callers.


def calculate_mrt_walk(
    address: str,
    mrt_station: str,
    token: str,
    *,
    opener=urlopen,
) -> dict[str, int | str]:
    """Return OneMap's walking distance and duration to the supplied MRT station."""
    if not address.strip() or not mrt_station.strip() or not token.strip():
        raise ValueError("address, mrt_station, and token are required")

    start = _geocode(address, token, opener)
    end = _geocode(mrt_station, token, opener)
    payload = _get_json(
        "/api/public/routingsvc/route",
        {
            "start": f"{start[0]},{start[1]}",
            "end": f"{end[0]},{end[1]}",
            "routeType": "walk",
        },
        token,
        opener,
    )

    try:
        summary = payload["route_summary"]
        seconds = round(float(summary["total_time"]))
        distance = round(float(summary["total_distance"]))
    except (KeyError, TypeError, ValueError) as error:
        raise OneMapError("OneMap returned an invalid walking route") from error

    return {
        "mrt_station": mrt_station,
        "mrt_walk_distance_m": distance,
        "mrt_walk_seconds": seconds,
        "mrt_walk_minutes": ceil(seconds / 60),
    }


def _geocode(query: str, token: str, opener) -> tuple[float, float]:
    payload = _get_json(
        "/api/common/elastic/search",
        {
            "searchVal": query,
            "returnGeom": "Y",
            "getAddrDetails": "N",
            "pageNum": 1,
        },
        token,
        opener,
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        raise OneMapNotFound(
            f"OneMap has no match for {query!r} (the API call itself succeeded)"
        )

    try:
        result = results[0]
        return float(result["LATITUDE"]), float(result["LONGITUDE"])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise OneMapError(f"OneMap returned an unusable match for {query!r}") from error


def _get_json(path: str, params: dict[str, object], token: str, opener) -> dict:
    request = Request(
        f"{_BASE_URL}{path}?{urlencode(params)}",
        headers={"Accept": "application/json", "Authorization": token},
    )
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as error:
        hint = " - token missing, wrong, or expired" if error.code in (401, 403) else ""
        raise OneMapError(
            f"OneMap {path} failed: HTTP {error.code}{hint}. {_body_snippet(error)}"
        ) from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise OneMapError(
            f"OneMap {path} failed: {type(error).__name__}: {error}"
        ) from error

    if not isinstance(payload, dict) or payload.get("error"):
        raise OneMapError(str(payload.get("error", "OneMap returned invalid JSON")))
    return payload


def _body_snippet(error: HTTPError, limit: int = 200) -> str:
    try:
        return error.read().decode("utf-8", "replace")[:limit].strip()
    except OSError:
        return ""


if __name__ == "__main__":
    from datetime import datetime

    result = get_token()
    expiry = int(result["expiry_timestamp"])
    print(result["access_token"])
    print(f"expires {datetime.fromtimestamp(expiry).astimezone():%Y-%m-%d %H:%M:%S %z}")
