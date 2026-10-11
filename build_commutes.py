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

The database's listing_commutes and nus_destinations tables are the source: a run first exports them
to commute_faculty.csv, fills in what is missing as above, and writes the result back. The CSV is in
Git, so a new database gets the same times without OneMap (setup_database.py imports it).

    python build_commutes.py --import   # put commute_faculty.csv into the database, e.g. after fix_transit_google.py
    python build_commutes.py --export   # write the database's commutes to commute_faculty.csv
"""

import csv
import os
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import sleep
from types import SimpleNamespace

from faculties import FACULTIES
from group_db import connect, open_database
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
# Minutes from each listing to each NUS faculty; the copy of the database's commutes, kept in Git.
COMMUTE_DATA = Path(__file__).with_name("commute_faculty.csv")

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


def _destination(faculty: dict) -> str:
    # The id src/dss5105/data/seed_nus_destinations.py gives each faculty, e.g. soc_default.
    return f"{faculty['code'].lower()}_default"


def _check_database_is_current(pg, path: Path = COMMUTE_DATA) -> None:
    """Stop before a run replaces path with a database that has fewer commutes than it."""
    in_database = pg.execute(
        "SELECT count(DISTINCT (listing_id, destination_id)) FROM listing_commutes WHERE destination_id = ANY(%s)",
        ([_destination(faculty) for faculty in FACULTIES],),
    ).fetchone()[0]
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            in_file = sum(1 for _ in csv.DictReader(file))
    except FileNotFoundError:
        in_file = 0
    if in_database < in_file:
        raise SystemExit(
            f"数据库里有 {in_database} 对通勤，比 {path.name} 的 {in_file} 行少，这次运行会用数据库的版本覆盖这个文件。\n"
            "要保留文件里的结果，先运行 python build_commutes.py --import；确定用数据库的版本，就先运行 --export。"
        )


def import_commutes(pg, path: Path = COMMUTE_DATA) -> int:
    """Make the database's commutes those in path; returns how many rows were written.

    The faculties' places are written from faculties.py too, so every time is measured to the
    building it was computed for. Commutes to these faculties computed elsewhere are replaced.
    Rows for listings the database does not have are left out.
    """
    destinations = {faculty["name"]: _destination(faculty) for faculty in FACULTIES}
    known = {listing_id for (listing_id,) in pg.execute("SELECT listing_id FROM listings")}
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            # A time still waiting for its walking check is left out, so the next run asks again.
            if (row["minutes"] and row.get("mode") == "") or row["listing_id"] not in known:
                continue
            mode = row.get("mode") or ("transit" if row["minutes"] else "")
            day, _, clock = (row.get("departure") or "").partition(" ")
            rows.append((
                row["listing_id"],
                destinations[row["faculty"]],
                "walk" if mode == "walk" else "transit",
                float(row["minutes"]) if row["minutes"] else None,
                "google" if mode == "transit_google" else "onemap",
                date.fromisoformat(day) if day else None,
                time.fromisoformat(clock) if clock else None,
            ))
    with pg.transaction(), pg.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO nus_destinations (destination_id, faculty_code, faculty_name, destination_name,
                address, postal_code, campus_area, latitude, longitude, is_default)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (destination_id) DO UPDATE SET
                faculty_code = EXCLUDED.faculty_code, faculty_name = EXCLUDED.faculty_name,
                destination_name = EXCLUDED.destination_name, address = EXCLUDED.address,
                postal_code = EXCLUDED.postal_code, campus_area = EXCLUDED.campus_area,
                latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, is_default = TRUE
            """,
            [
                (_destination(faculty), faculty["code"], faculty["name"], faculty["building"], faculty["address"],
                 faculty["address"][-6:], faculty["campus"], faculty["latitude"], faculty["longitude"])
                for faculty in FACULTIES
            ],
        )
        cursor.execute("DELETE FROM listing_commutes WHERE destination_id = ANY(%s)", (list(destinations.values()),))
        cursor.executemany(
            """
            INSERT INTO listing_commutes (listing_id, destination_id, travel_mode, duration_min,
                route_provider, benchmark_date, benchmark_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


def export_commutes(pg, path: Path = COMMUTE_DATA) -> int:
    """Write the database's commutes to path, one row per listing and faculty; returns the row count."""
    rows: dict[tuple[str, str], dict] = {}
    for listing_id, faculty, minutes, travel_mode, provider, day, clock in pg.execute(
        """
        SELECT c.listing_id, d.faculty_name, c.duration_min, c.travel_mode, c.route_provider,
            c.benchmark_date, c.benchmark_time
        FROM listing_commutes c JOIN nus_destinations d USING (destination_id)
        ORDER BY c.listing_id, d.faculty_code, c.travel_mode
        """
    ):
        row = {
            "listing_id": listing_id,
            "faculty": faculty,
            "minutes": "" if minutes is None else f"{float(minutes):g}",
            # Empty when there is no route, as build() writes it.
            "mode": "" if minutes is None else "walk" if travel_mode == "walk" else "transit_google" if provider == "google" else "transit",
            "departure": (f"{day:%Y-%m-%d}" + (f" {clock:%H:%M}" if clock else "")) if day else "",
        }
        # Should both a walking and a public-transport row exist, the faster is kept.
        known = rows.get((listing_id, faculty))
        if known is None or not known["minutes"] or (row["minutes"] and _faster(row, known)):
            rows[listing_id, faculty] = row
    _save(path, rows)
    return len(rows)


def _faster(row: dict, known: dict) -> bool:
    """Walking wins only when strictly faster, as build() decides and the agent_listings view reads it."""
    if float(row["minutes"]) != float(known["minutes"]):
        return float(row["minutes"]) < float(known["minutes"])
    return known["mode"] == "walk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    flags = sys.argv[1:]
    if flags in (["--import"], ["--export"]):
        with closing(connect()) as pg:
            if flags == ["--import"]:
                print(f"已把 {COMMUTE_DATA.name} 的 {import_commutes(pg)} 行写入数据库。")
            else:
                print(f"已把数据库里的 {export_commutes(pg)} 行通勤写入 {COMMUTE_DATA.name}。")
        return
    chosen = next((flag.split("=", 1)[1] for flag in flags if flag.startswith("--date=")), None)
    if len(flags) > (1 if chosen else 0):
        raise SystemExit("Usage: python build_commutes.py [--date=YYYY-MM-DD] | --import | --export")
    departure = datetime(*date.fromisoformat(chosen).timetuple()[:3], *DEPARTURE_TIME) if chosen else next_weekday_morning(date.today())
    with closing(open_database()) as database:
        listings = load_listings(database)
    # The database is the source; the CSV is the working copy for this run.
    with closing(connect()) as pg:
        _check_database_is_current(pg)
        print(f"从数据库导出 {export_commutes(pg)} 行到 {COMMUTE_DATA.name}。")
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
    finally:
        # Also after an error: what was asked so far reaches the database, on a new connection
        # since the run takes about an hour.
        with closing(connect()) as pg:
            print(f"已把 {import_commutes(pg)} 行写回数据库。")
    print(f"完成：查询公共交通路线 {asked['transit']} 条、步行路线 {asked['walk']} 条，其中 {asked['walk_faster']} 对步行更快。")


if __name__ == "__main__":
    main()
