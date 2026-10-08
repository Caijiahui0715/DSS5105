"""Print OneMap's public-transport trips from a listing to a faculty, leg by leg.

    python show_route.py 24611200 牙医学院
    python show_route.py 24611200 "Faculty of Dentistry" --date=2026-10-12

For checking a commute time that looks wrong: every trip OneMap offers, with each leg's mode,
start, end and minutes, and the walking route for comparison. Nothing is saved.
"""

import sys
from contextlib import closing
from datetime import date, datetime

from build_commutes import DEPARTURE_TIME, next_weekday_morning
from faculties import find_faculty
from group_db import open_listings
from onemap import load_token, public_transport_plan, walking_minutes
from tools import get_listings_by_ids


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    chosen = next((arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--date=")), None)
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--date=")]
    if len(names) != 2:
        raise SystemExit("Usage: python show_route.py LISTING_ID FACULTY [--date=YYYY-MM-DD]")
    with closing(open_listings()) as connection:
        listings = get_listings_by_ids(connection, [names[0]])
    faculty = find_faculty(names[1])
    if not listings or listings[0].get("latitude") is None:
        raise SystemExit(f"找不到房源 {names[0]}，或它没有坐标。")
    if not faculty:
        raise SystemExit(f"不认识学院 {names[1]!r}，请用 faculties.py 里的名称。")
    listing = listings[0]
    departure = datetime(*date.fromisoformat(chosen).timetuple()[:3], *DEPARTURE_TIME) if chosen else next_weekday_morning(date.today())
    start, end = (listing["latitude"], listing["longitude"]), (faculty["latitude"], faculty["longitude"])
    token = load_token()

    print(f"从 {listing.get('title')}（{listing['listing_id']}，{listing.get('address')}，坐标 {start[0]:.6f},{start[1]:.6f}）")
    print(f"到 {faculty['zh']}（{faculty['building']}，{faculty['address']}），{departure:%Y-%m-%d %H:%M} 出发")
    walked = walking_minutes(start, end, token)
    print(f"直接步行：{'约 %d 分钟' % walked if walked is not None else 'OneMap 没有找到步行路线'}")
    plan = public_transport_plan(start, end, token, departure)
    itineraries = ((plan or {}).get("plan") or {}).get("itineraries") or []
    if not itineraries:
        print("公共交通：OneMap 没有找到路线")
        return
    for number, trip in enumerate(itineraries, 1):
        print(
            f"\n方案 {number}：共 {trip['duration'] / 60:.0f} 分钟"
            f"（步行 {trip.get('walkTime', 0) / 60:.0f}，乘车 {trip.get('transitTime', 0) / 60:.0f}，等车 {trip.get('waitingTime', 0) / 60:.0f}），"
            f"步行共 {trip.get('walkDistance', 0):.0f} 米"
        )
        for leg in trip.get("legs", []):
            line = leg.get("route") or leg.get("routeShortName") or ""
            print(
                f"  {leg.get('mode', '?'):7} {line:6} {leg.get('from', {}).get('name', '?')} → {leg.get('to', {}).get('name', '?')}"
                f"  {leg.get('duration', 0) / 60:.0f} 分钟  {leg.get('distance', 0):.0f} 米"
            )


if __name__ == "__main__":
    main()
