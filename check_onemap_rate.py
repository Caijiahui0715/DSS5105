"""How many OneMap routing calls a minute this account gets, for ONEMAP_CALLS_PER_MINUTE in .env.

    python check_onemap_rate.py         # up to 300 walking routes in one minute, 6 at a time

The backend works out routes to a place a user names (place_routes.py) at ONEMAP_CALLS_PER_MINUTE,
240 without it. This asks OneMap for a short walking route as fast as six requests at a time allow,
for at most a minute or 300 calls, and stops at the first "too many requests" (HTTP 429). It prints
how many calls got through and a value to put in .env. The token is loaded as the backend loads it
and never printed. Run it once, not while the backend is busy working out routes.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from faculties import find_faculty
from onemap import OneMapError, load_token, walking_minutes

_CALLS = 300
_SECONDS = 60
_WORKERS = 6


def main() -> int:
    try:
        token = load_token()
    except OneMapError as error:
        print(f"Could not get a OneMap token: {error}")
        return 1
    # A short walk on campus: from the School of Computing to the Business School.
    start, end = (find_faculty(name) for name in ("School of Computing", "NUS Business School"))
    route = ((start["latitude"], start["longitude"]), (end["latitude"], end["longitude"]))
    lock = threading.Lock()
    done, limited, other_errors = [], [], []
    began = time.monotonic()

    def call(_):
        if limited or time.monotonic() - began > _SECONDS:
            return
        try:
            walking_minutes(*route, token)
        except OneMapError as error:
            with lock:
                (limited if "HTTP 429" in str(error) else other_errors).append((time.monotonic() - began, str(error)[:120]))
            return
        with lock:
            done.append(time.monotonic() - began)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        list(pool.map(call, range(_CALLS)))
    elapsed = time.monotonic() - began
    if other_errors:
        print(f"{len(other_errors)} calls failed for reasons other than the rate limit: {other_errors[0][1]}")
    if limited:
        at = limited[0][0]
        print(f"OneMap started limiting (HTTP 429) {at:.1f} seconds in, after {len(done)} successful calls.")
        per_minute = len(done) if at <= 60 else round(len(done) * 60 / at)
        print(f"The limit is about {per_minute} calls a minute. Suggested setting in .env: ONEMAP_CALLS_PER_MINUTE={max(int(per_minute * 0.9), 1)}")
    else:
        rate = round(len(done) * 60 / elapsed) if elapsed else len(done)
        print(f"{len(done)} successful calls in {elapsed:.1f} seconds without being limited, about {rate} a minute.")
        print("The limit is at least that; keep the default of 240, or set ONEMAP_CALLS_PER_MINUTE from this result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
