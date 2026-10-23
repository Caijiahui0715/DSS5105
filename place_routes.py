"""Commute times to a place a user names as the other destination (a gym, an office), worked out
with OneMap the first time and kept in the place_routes table, so the same place is not asked again.

As build_commutes.py does for the faculties, a trip leaves at 08:30 on the next weekday by public
transport, and a place within 1.5 km in a straight line also gets a walking route, kept when it is
faster. A search works out only the listings it may show (decision.route_candidates), a few at a
time, all under one rate for the whole backend: ONEMAP_CALLS_PER_MINUTE in .env, 240 without it.
When OneMap answers that there are too many requests, every call waits a while and tries again.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from math import ceil

from build_commutes import WALK_CHECK_M, next_weekday_morning
from config import env
from group_db import Database
from models import Destination, Listing
from onemap import OneMapError, load_token, public_transport_minutes, walking_minutes
from tools import location_distance_m, place_key

# Requests at once; the rate below is what limits them.
WORKERS = 6
# More listings than this to work out and the user is asked first (about 30 seconds at the default rate).
ASK_ABOVE = 120
_BACKOFF_SECONDS = 10
_ATTEMPTS = 4


def _calls_per_minute() -> int:
    try:
        return max(int(env("ONEMAP_CALLS_PER_MINUTE") or 240), 1)
    except ValueError:
        return 240


class RateLimiter:
    """At most calls_per_minute calls, evenly spaced, across every thread of the backend."""

    def __init__(self, calls_per_minute: int):
        self.interval = 60 / calls_per_minute
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        time.sleep(start - now)

    def back_off(self, seconds: float | None = None) -> None:
        """No call for a while: OneMap said there were too many."""
        seconds = _BACKOFF_SECONDS if seconds is None else seconds
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


LIMITER = RateLimiter(_calls_per_minute())


def seconds_for(count: int) -> int:
    """About how long working out count listings takes at the shared rate."""
    return ceil(count * LIMITER.interval)


def _call(function, *args):
    """One OneMap call within the shared rate; "too many requests" waits and asks again."""
    for attempt in range(_ATTEMPTS):
        LIMITER.wait()
        try:
            return function(*args)
        except OneMapError as error:
            if "HTTP 429" not in str(error) or attempt == _ATTEMPTS - 1:
                raise
            LIMITER.back_off()


def onemap_trip(listing: Listing, destination: Destination, token: str, departure: datetime) -> dict | None:
    """The faster trip from the listing to the place, {"minutes", "mode"}; None when OneMap has no route."""
    start, end = (listing["latitude"], listing["longitude"]), (destination.latitude, destination.longitude)
    transit = _call(public_transport_minutes, start, end, token, departure)
    trip = None if transit is None else {"minutes": transit, "mode": "transit"}
    distance = location_distance_m(listing, destination)
    if distance is not None and distance <= WALK_CHECK_M:
        walk = _call(walking_minutes, start, end, token)
        # Walking only when strictly faster, as build_commutes.py decides.
        if walk is not None and (transit is None or walk < transit):
            trip = {"minutes": walk, "mode": "walk"}
    return trip


def onemap_router():
    """route(listing, destination) with OneMap; the token is loaded on first use."""
    token = None

    def route(listing: Listing, destination: Destination) -> dict | None:
        nonlocal token
        token = token or load_token()
        return onemap_trip(listing, destination, token, next_weekday_morning(date.today()))

    return route


def missing(connection: Database, destination: Destination, listings: list[Listing]) -> list[Listing]:
    """The listings with a position that have no route to the place on file yet."""
    located = [listing for listing in listings if listing.get("latitude") is not None and listing.get("longitude") is not None]
    if not located:
        return []
    known = {
        row["listing_id"]
        for row in connection.query(
            "SELECT listing_id FROM place_routes WHERE place_key = %s AND listing_id = ANY(%s)",
            [place_key(destination.latitude, destination.longitude), [listing["listing_id"] for listing in located]],
        )
    }
    return [listing for listing in located if listing["listing_id"] not in known]


def work_out(connection: Database, destination: Destination, listings: list[Listing], route, progress=None) -> dict:
    """Routes from each listing to the place, a few at a time, each kept as it arrives; progress(done,
    total) after each. A route that fails is not kept, so the next search asks again."""
    key = place_key(destination.latitude, destination.longitude)
    departure = f"{next_weekday_morning(date.today()):%Y-%m-%d %H:%M}"
    done = failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(route, listing, destination): listing for listing in listings}
        for future in as_completed(futures):
            done += 1
            try:
                trip = future.result()
            except Exception:  # OneMap down, a token problem: asked again next time.
                failed += 1
            else:
                connection.run(
                    "INSERT INTO place_routes VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (place_key, listing_id) DO UPDATE SET "
                    "minutes = EXCLUDED.minutes, mode = EXCLUDED.mode, departure = EXCLUDED.departure, checked_at = EXCLUDED.checked_at",
                    [key, futures[future]["listing_id"], trip and trip["minutes"], trip and trip["mode"], departure,
                     datetime.now(timezone.utc).isoformat()],
                )
            if progress:
                progress(done, len(listings))
    return {"worked_out": done - failed, "failed": failed}
