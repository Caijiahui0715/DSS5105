"""Minutes from every listing to every NUS faculty, for commute questions.

    python build_commutes.py                    # leaving 08:30 on the next weekday
    python build_commutes.py --date=2026-10-12  # leaving 08:30 on that day

Writes commute_faculty.csv next to this file, one row per listing and faculty: listing_id,
faculty, minutes, mode, departure. minutes is OneMap's public-transport trip (mode transit), or
its walking route (mode walk) when the faculty is within 1.5 km in a straight line and walking is
faster. An empty minutes cell means there is no usable route.

Running again keeps what is saved and only asks OneMap for what is missing: listings added by a
data refresh, walking checks a file from before them lacks, or a run that stopped part-way.
Progress is saved as it goes. A full run is about 6,000 routes and takes about an hour.
"""

import csv
import os
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from time import sleep
from types import SimpleNamespace

from faculties import FACULTIES
from mock_db import COMMUTE_DATA, create_database
from onemap import OneMapError, load_token, public_transport_minutes, walking_minutes
from tools import load_listings, location_distance_m

DEPARTURE_TIME = (8, 30)
# Within this straight-line distance walking can beat public transport, so both are asked.
WALK_CHECK_M = 1500
# OneMap's public-transport routes from 49 Normanton Park took 81-110 minutes to faculties
# 1.5-4.6 km away, where other listings at those distances take 25-37 (checked 2026-10-07).
# OneMap is not asked for them: fix_transit_google.py fills their rows from Google's Routes API
# (mode transit_google), and a rerun keeps those rows.
UNRELIABLE_TRANSIT = {"24611200", "24666342"}
_PAUSE_SECONDS = 0.25
_SAVE_EVERY = 25
_FIELDS = ("listing_id", "faculty", "minutes", "mode", "departure")

Point = tuple[float, float]


def next_weekday_morning(today: date) -> datetime:
    day = today + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, *DEPARTURE_TIME)


def build(
    listings: list[dict],
    path: Path,
    departure: datetime,
    route: Callable[[Point, Point, datetime], int | None],
    walk: Callable[[Point, Point], int | None],
    pause: float = 0.0,
) -> dict[str, int]:
    """Fill in what path is missing; return how many transit and walking routes were asked."""
    rows = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                # A file from before walking checks has no mode column.
                rows[row["listing_id"], row["faculty"]] = {field: row.get(field) or "" for field in _FIELDS}
    asked = {"transit": 0, "walk": 0, "walk_faster": 0}
    unsaved = 0
    try:
        for listing in listings:
            if listing.get("latitude") is None or listing.get("longitude") is None:
                continue
            start = (listing["latitude"], listing["longitude"])
            for faculty in FACULTIES:
                end = (faculty["latitude"], faculty["longitude"])
                place = SimpleNamespace(latitude=end[0], longitude=end[1])
                near = location_distance_m(listing, place) <= WALK_CHECK_M
                key = (listing["listing_id"], faculty["name"])
                row = rows.get(key)
                if row is None:
                    minutes = None
                    if listing["listing_id"] not in UNRELIABLE_TRANSIT:
                        minutes = route(start, end, departure)
                        asked["transit"] += 1
                        unsaved += 1
                        sleep(pause)
                    row = rows[key] = {
                        "listing_id": key[0],
                        "faculty": key[1],
                        "minutes": "" if minutes is None else minutes,
                        "mode": "",
                        "departure": f"{departure:%Y-%m-%d %H:%M}",
                    }
                # mode stays empty until a near pair's walking check is done.
                if row["mode"] == "" and near:
                    walked = walk(start, end)
                    asked["walk"] += 1
                    unsaved += 1
                    sleep(pause)
                    if walked is not None and (row["minutes"] == "" or walked < float(row["minutes"])):
                        row["minutes"], row["mode"] = walked, "walk"
                        asked["walk_faster"] += 1
                    elif row["minutes"] != "":
                        row["mode"] = "transit"
                elif row["mode"] == "" and row["minutes"] != "":
                    row["mode"] = "transit"
                if unsaved >= _SAVE_EVERY:
                    _save(path, rows)
                    unsaved = 0
    finally:
        # Also when OneMap fails part-way: everything asked so far is kept.
        _save(path, rows)
    return asked


def _save(path: Path, rows: dict) -> None:
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())
    # Replaced in one step, so an interrupted save never leaves half a file.
    os.replace(partial, path)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    flags = sys.argv[1:]
    chosen = next((flag.split("=", 1)[1] for flag in flags if flag.startswith("--date=")), None)
    if len(flags) > (1 if chosen else 0):
        raise SystemExit("Usage: python build_commutes.py [--date=YYYY-MM-DD]")
    departure = datetime(*date.fromisoformat(chosen).timetuple()[:3], *DEPARTURE_TIME) if chosen else next_weekday_morning(date.today())
    with closing(create_database()) as connection:
        listings = load_listings(connection)
    print(f"补全 {COMMUTE_DATA.name}：新路线按 {departure:%Y-%m-%d %H:%M} 出发的公共交通计算，1.5 公里内的学院再查步行路线。")
    token = load_token()
    try:
        asked = build(
            listings,
            COMMUTE_DATA,
            departure,
            lambda start, end, when: public_transport_minutes(start, end, token, when),
            lambda start, end: walking_minutes(start, end, token),
            pause=_PAUSE_SECONDS,
        )
    except OneMapError as error:
        raise SystemExit(f"OneMap 出错：{error}\n已查到的结果都已保存，稍后再运行一次会从中断处继续。") from error
    print(f"完成：查询公共交通路线 {asked['transit']} 条、步行路线 {asked['walk']} 条，其中 {asked['walk_faster']} 对步行更快。")


if __name__ == "__main__":
    main()
