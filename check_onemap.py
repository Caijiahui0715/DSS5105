"""Smoke-test the OneMap setup end to end.

    python check_onemap.py
    python check_onemap.py "460 Clementi Avenue 3" "Clementi MRT Station"

Exits 0 when the API is usable, 1 when it is not. A query that simply has no
match is reported as WARN, not FAIL: it means the API works and the address
needs fixing.
"""

import sys
from datetime import datetime, timezone
from urllib.request import urlopen

from onemap import (
    OneMapError,
    OneMapNotFound,
    _geocode,
    _get_json,
    calculate_mrt_walk,
    load_token,
    token_expiry,
)

# OneMap's own documented sample query, so this probe tests the API and never
# the address: searchVal=200640 -> "640 ROWELL ROAD SINGAPORE 200640".
_PROBE = "200640"
_ADDRESS = "200640"
_STATION = "Farrer Park MRT Station"

_PASS, _WARN, _FAIL = "PASS", "WARN", "FAIL"


def _report(step: str, status: str, detail: str) -> str:
    print(f"[{status}] {step:8} {detail}")
    return status


def main(argv: list[str]) -> int:
    address = argv[1] if len(argv) > 1 else _ADDRESS
    station = argv[2] if len(argv) > 2 else _STATION
    statuses = []

    # 1. Is there a token, and is it still in date? No network call.
    try:
        token = load_token()
    except OneMapError as error:
        _report("token", _FAIL, str(error))
        print("\nOneMap API is NOT usable - see the FAIL line above.")
        return 1

    expiry = token_expiry(token)
    if expiry is None:
        statuses.append(_report("token", _PASS, f"{len(token)} chars, expiry claim unreadable"))
    else:
        hours_left = (expiry - datetime.now(timezone.utc).timestamp()) / 3600
        local = datetime.fromtimestamp(expiry).astimezone()
        statuses.append(
            _report(
                "token",
                _PASS if hours_left > 0 else _FAIL,
                f"expires {local:%Y-%m-%d %H:%M} (UTC{local:%z}), {hours_left:.1f}h left",
            )
        )

    # 2. Does the token actually open the API? A bad token fails here with 401.
    try:
        payload = _get_json(
            "/api/common/elastic/search",
            {"searchVal": _PROBE, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1},
            token,
            urlopen,
        )
        found = payload.get("found", 0)
        statuses.append(
            _report("auth", _PASS, f"search accepted the token (sample {_PROBE!r}: {found} found)")
        )
    except OneMapError as error:
        statuses.append(_report("auth", _FAIL, str(error)))
        print("\nOneMap API is NOT usable - see the FAIL line above.")
        return 1

    # 3. Does the address you care about resolve?
    try:
        latitude, longitude = _geocode(address, token, urlopen)
        statuses.append(_report("geocode", _PASS, f"{address!r} -> {latitude}, {longitude}"))
    except OneMapNotFound as error:
        statuses.append(_report("geocode", _WARN, str(error)))
    except OneMapError as error:
        statuses.append(_report("geocode", _FAIL, str(error)))

    # 4. The routing call the agent actually makes.
    try:
        walk = calculate_mrt_walk(address, station, token, opener=urlopen)
        statuses.append(
            _report(
                "routing",
                _PASS,
                f"{walk['mrt_walk_distance_m']} m / {walk['mrt_walk_minutes']} min to {station}",
            )
        )
    except OneMapNotFound as error:
        statuses.append(_report("routing", _WARN, str(error)))
    except OneMapError as error:
        statuses.append(_report("routing", _FAIL, str(error)))

    print()
    if _FAIL in statuses:
        print("OneMap API is NOT usable - see the FAIL lines above.")
        return 1
    if _WARN in statuses:
        print("OneMap API is working. A query had no match - fix the address, not the setup.")
        return 0
    print("OneMap API is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
