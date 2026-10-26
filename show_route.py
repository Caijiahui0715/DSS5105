"""Print OneMap's public-transport trips from a listing to a faculty, leg by leg.

    python show_route.py 24611200 Dentistry
    python show_route.py 24611200 "Faculty of Dentistry" --date=2026-10-12

For checking a commute time that looks wrong: every trip OneMap offers, with each leg's mode,
start, end and minutes, and the walking route for comparison. Nothing is saved.
"""

import sys
from contextlib import closing
from datetime import date, datetime

from build_commutes import DEPARTURE_TIME, next_weekday_morning
from faculties import find_faculty
from group_db import open_database
from onemap import load_token, public_transport_plan, walking_minutes
from tools import get_listings_by_ids


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    chosen = next((arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--date=")), None)
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--date=")]
    if len(names) != 2:
        raise SystemExit("Usage: python show_route.py LISTING_ID FACULTY [--date=YYYY-MM-DD]")
    with closing(open_database()) as database:
        listings = get_listings_by_ids(database, [names[0]])
    faculty = find_faculty(names[1])
    if not listings or listings[0].get("latitude") is None:
        raise SystemExit(f"Listing {names[0]} was not found, or it has no coordinates.")
    if not faculty:
        raise SystemExit(f"Unknown faculty {names[1]!r}; use a name from faculties.py.")
    listing = listings[0]
    departure = datetime(*date.fromisoformat(chosen).timetuple()[:3], *DEPARTURE_TIME) if chosen else next_weekday_morning(date.today())
    start, end = (listing["latitude"], listing["longitude"]), (faculty["latitude"], faculty["longitude"])
    token = load_token()

    print(f"From {listing.get('title')} ({listing['listing_id']}, {listing.get('address')}, coordinates {start[0]:.6f},{start[1]:.6f})")
    print(f"To {faculty['name']} ({faculty['building']}, {faculty['address']}), leaving {departure:%Y-%m-%d %H:%M}")
    walked = walking_minutes(start, end, token)
    print(f"Walking all the way: {'about %d min' % walked if walked is not None else 'OneMap found no walking route'}")
    plan = public_transport_plan(start, end, token, departure)
    itineraries = ((plan or {}).get("plan") or {}).get("itineraries") or []
    if not itineraries:
        print("Public transport: OneMap found no route")
        return
    for number, trip in enumerate(itineraries, 1):
        print(
            f"\nTrip {number}: {trip['duration'] / 60:.0f} min in all"
            f" (walking {trip.get('walkTime', 0) / 60:.0f}, riding {trip.get('transitTime', 0) / 60:.0f}, waiting {trip.get('waitingTime', 0) / 60:.0f}),"
            f" {trip.get('walkDistance', 0):.0f} m on foot"
        )
        for leg in trip.get("legs", []):
            line = leg.get("route") or leg.get("routeShortName") or ""
            print(
                f"  {leg.get('mode', '?'):7} {line:6} {leg.get('from', {}).get('name', '?')} → {leg.get('to', {}).get('name', '?')}"
                f"  {leg.get('duration', 0) / 60:.0f} min  {leg.get('distance', 0):.0f} m"
            )


if __name__ == "__main__":
    main()
