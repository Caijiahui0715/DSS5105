import csv
import tempfile
import unittest
from bisect import bisect_left
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import group_db
from build_commutes import COMMUTE_DATA, _check_database_is_current, export_commutes, import_commutes
from faculties import FACULTIES
from mock_db import create_database, create_mock_database, database_name, plain_connection, reopened
from models import AMENITY_FIELDS
from tools import get_listings_by_ids, load_listings, validate_ranked_listings

_HEADER = "listing_id,faculty,minutes,mode,departure\n"


def positions(listings, field):
    """Each listing's position on field among those stating it: 0 has the most, 1 the fewest."""
    values = sorted(listing[field] for listing in listings if listing[field] is not None)
    return {
        listing["listing_id"]: 1 - bisect_left(values, listing[field]) / len(values)
        for listing in listings
        if listing[field] is not None
    }


def space_ranks(listings):
    """Area percentile, largest first, among listings of the same scope whose area is the rented space."""
    groups = {}
    for listing in listings:
        if (listing["rental_scope"], listing["area_scope"]) in {("entire_unit", "floor_reported"), ("room", "room_reported")} and (listing["area_sqm"] or 0) > 0:
            groups.setdefault((listing["rental_scope"], listing["area_scope"]), []).append(listing)
    ranks = {}
    for group in groups.values():
        for listing in group:
            larger = sum(other["area_sqm"] > listing["area_sqm"] for other in group)
            ranks[listing["listing_id"]] = larger / (len(group) - 1) if len(group) > 1 else 0
    return ranks


class AgentListingsViewTest(unittest.TestCase):
    def assertRanks(self, listings, field, expected):
        for listing in listings:
            actual, wanted = listing[field], expected.get(listing["listing_id"])
            self.assertEqual(actual is None, wanted is None, (listing["listing_id"], field))
            if wanted is not None:
                self.assertAlmostEqual(actual, wanted, 9, (listing["listing_id"], field))

    def test_ranks_are_relative_to_every_active_listing(self):
        with closing(create_database()) as database:
            listings = load_listings(database)

        for name, field in AMENITY_FIELDS.items():
            self.assertRanks(listings, f"{name}_rank", positions(listings, field))
        food = [positions(listings, field) for field in ("poi_fnb_1km", "poi_hawker_1km")]
        expected = {}
        for listing in listings:
            shares = [ranks[listing["listing_id"]] for ranks in food if listing["listing_id"] in ranks]
            if shares:
                expected[listing["listing_id"]] = round(sum(shares) / len(shares), 3)
        self.assertRanks(listings, "food_rank", expected)
        self.assertRanks(listings, "space_rank", space_ranks(listings))
        # The rechecked rent is the one searched; the card's stays for evidence.
        changed = next(listing for listing in listings if listing["rent_monthly_sgd_now"] not in (None, listing["rent_monthly_sgd_card"]))
        self.assertEqual(changed["rent_monthly_sgd"], changed["rent_monthly_sgd_now"])

    def test_walking_is_used_only_when_strictly_faster(self):
        codes = {faculty["name"]: f"{faculty['code'].lower()}_default" for faculty in FACULTIES}
        with tempfile.TemporaryDirectory() as folder:
            # Faculties only, no commutes yet.
            empty = Path(folder) / "commute_faculty.csv"
            empty.write_text(_HEADER, encoding="utf-8")
            with closing(create_database(commute_path=empty)) as database:
                listing_id = load_listings(database)[0]["listing_id"]
                for faculty, mode, minutes in (
                    ("Faculty of Law", "transit", 20),
                    ("Faculty of Law", "walk", 20),
                    ("Faculty of Science", "walk", 12),
                    ("Faculty of Science", "transit", 18),
                ):
                    database.run(
                        "INSERT INTO listing_commutes (listing_id, destination_id, travel_mode, duration_min) VALUES (%s, %s, %s, %s)",
                        (listing_id, codes[faculty], mode, minutes),
                    )
                (listing,) = get_listings_by_ids(database, [listing_id])

        self.assertEqual(listing["commutes"], {
            "Faculty of Law": {"minutes": 20, "mode": "transit"},
            "Faculty of Science": {"minutes": 12, "mode": "walk"},
        })

    def test_link_checks_are_kept_for_the_next_start(self):
        with closing(create_mock_database()) as database:
            database.run("DELETE FROM listing_health")
            listing = load_listings(database)[0]
            checked = validate_ranked_listings(
                database, [{"listing": listing}], lambda listing_id, url: {"status": "active", "final_url": url, "http_status": 200}
            )
            # A restarted server reuses the check instead of opening the link again.
            with closing(reopened("mock")) as again:
                never = lambda *_: self.fail("the link was checked again")
                reused = validate_ranked_listings(again, [{"listing": listing}], never)

        self.assertEqual(checked["summary"]["active_count"], 1)
        self.assertEqual(reused["summary"]["active_count"], 1)


class ConnectionTest(unittest.TestCase):
    def test_connections_the_server_dropped_are_replaced(self):
        with closing(create_mock_database()) as database:
            self.assertEqual(len(load_listings(database)), 12)
            # As when PostgreSQL restarts: every connection to the test database is closed.
            with closing(plain_connection("mock")) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (database_name(),),
                )
            self.assertEqual(len(load_listings(database)), 12)

    def test_a_server_that_cannot_be_reached_stops_the_start_with_what_to_fix(self):
        settings = {**group_db.postgres_settings(), "host": "127.0.0.1", "port": "1", "connect_timeout": "2"}
        with patch("group_db.postgres_settings", return_value=settings), self.assertRaises(SystemExit) as stopped:
            group_db.open_database()

        self.assertIn("连不上 PostgreSQL", str(stopped.exception))
        self.assertIn("DB_HOST", str(stopped.exception))

    def test_a_database_without_listing_tables_says_to_run_the_setup(self):
        # The test database's public schema has no tables: tests keep theirs in schemas of their own.
        create_mock_database().close()
        settings = {**group_db.postgres_settings(), "dbname": database_name()}
        with patch("group_db.postgres_settings", return_value=settings), self.assertRaises(SystemExit) as stopped:
            group_db.open_database()

        self.assertIn("setup_database.py", str(stopped.exception))


class CommuteTablesTest(unittest.TestCase):
    def test_import_then_export_gives_the_same_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            empty, path = Path(folder) / "empty.csv", Path(folder) / "commute_faculty.csv"
            empty.write_text(_HEADER, encoding="utf-8")
            with closing(create_database(commute_path=empty)), closing(plain_connection("commutes")) as pg:
                # A run would replace the CSV with the database's commutes, here none: it stops.
                with self.assertRaises(SystemExit):
                    _check_database_is_current(pg)
                imported = import_commutes(pg)
                _check_database_is_current(pg)
                export_commutes(pg, path)
                destinations = pg.execute("SELECT destination_id, faculty_code FROM nus_destinations").fetchall()
                google = pg.execute(
                    "SELECT travel_mode, route_provider, benchmark_time FROM listing_commutes "
                    "WHERE listing_id = '24611200' AND destination_id = 'law_default'"
                ).fetchone()
            with path.open(encoding="utf-8", newline="") as file:
                again = {(row["listing_id"], row["faculty"]): row for row in csv.DictReader(file)}
        with COMMUTE_DATA.open(encoding="utf-8-sig", newline="") as file:
            original = {(row["listing_id"], row["faculty"]): row for row in csv.DictReader(file)}

        self.assertEqual(imported, len(original))
        self.assertEqual(again, original)
        # Faculty places come from faculties.py, codes included, under the ids the seed script uses.
        self.assertEqual({code for _, code in destinations}, {faculty["code"] for faculty in FACULTIES})
        self.assertIn(("soc_default", "SOC"), destinations)
        self.assertEqual(google, ("transit", "google", None))


if __name__ == "__main__":
    unittest.main()
