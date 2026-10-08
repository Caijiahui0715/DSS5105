import csv
import json
import tempfile
import unittest
from contextlib import closing, nullcontext
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import group_db
from build_commutes import _check_database_is_current, export_commutes, import_commutes
from faculties import FACULTIES
from group_db import LiveListings, load
from mock_db import COMMUTE_DATA, DEFAULT_FINAL_DATA, V1_DATA, create_database
from tools import coordinate_error_m, load_listings

# Column types of the group database (src/dss5105/database/schema.sql and migration_v2.sql).
_NUMERIC = {"rent_monthly_sgd", "area_sqm", "mrt_distance_m", "rent_monthly_sgd_now", "pg_school_nearest_walk_m",
            "pg_school_nearest_walk_min", "pg_mrt_nearest_walk_m", "coord_error_m"}
_INTEGER = {"bedrooms", "bathrooms", "mrt_minutes_reported", "tenant_count_reported", "poi_hawker_1km", "poi_library_1km",
            "poi_sport_1km", "poi_healthcare_1km", "poi_community_1km", "poi_fnb_1km", "pg_school_count", "pg_mrt_count"}
_FLOAT = {"latitude", "longitude"}


def as_postgres(field, text):
    """A V2 CSV cell as psycopg returns it from the group database."""
    if text in ("", None):
        return None
    if field in _NUMERIC:
        # sync_v2.py stores "~500" as 500.
        return Decimal(text.lstrip("~")).quantize(Decimal("0.01"))
    if field in _INTEGER:
        return int(float(text))
    if field in _FLOAT:
        return float(text)
    if field == "listed_date":
        return date.fromisoformat(text)
    if field in ("collected_at", "enriched_at"):
        return datetime.fromisoformat(text)
    return text


class Cursor:
    def __init__(self, rows, names=(), connection=None):
        self.rows, self.description, self.connection = rows, [(name,) for name in names] or None, connection

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return self.rows[0]

    def executemany(self, sql, rows):
        self.connection.written.append((sql, list(rows)))

    def execute(self, sql, params=()):
        self.connection.written.append((sql, [params]))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePostgres:
    """The group database's tables, filled from the CSV files, answering group_db's queries."""

    closed = False

    def __init__(self, fingerprint="first"):
        self.fingerprint, self.written, self.health, self.fail, self.drops = fingerprint, [], {}, False, 0
        with DEFAULT_FINAL_DATA.open(encoding="utf-8-sig", newline="") as file:
            self.listings = [{field: as_postgres(field, value) for field, value in row.items()} for row in csv.DictReader(file)]
        v1 = json.loads(V1_DATA.read_text(encoding="utf-8"))
        metadata = {row["listing_id"]: row for row in v1["listing_metadata"]}
        for listing in self.listings:
            listing.update({key: metadata[listing["listing_id"]][key] for key in ("availability_status", "review_flags")})
        self.districts = [(row["district_code"], row["district"]) for row in v1["district_lookup"]]
        self.commutes = []
        with COMMUTE_DATA.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if row["minutes"]:
                    travel_mode = "walk" if row["mode"] == "walk" else "transit"
                    provider = "google" if row["mode"] == "transit_google" else "onemap"
                    self.commutes.append((row["listing_id"], row["faculty"], travel_mode, provider, Decimal(row["minutes"])))

    def execute(self, sql, params=()):
        if self.fail or self.drops:
            self.drops = max(0, self.drops - 1)
            raise ConnectionError("server closed the connection")
        if sql == group_db._LISTINGS:
            names = list(self.listings[0])
            return Cursor([[row[name] for name in names] for row in sorted(self.listings, key=lambda row: row["listing_id"])], names)
        if sql == group_db._SAVE_HEALTH:
            self.health[params[0]] = params
            return Cursor([])
        answers = {
            group_db._DISTRICTS: self.districts,
            group_db._COMMUTES: self.commutes,
            group_db._HEALTH: list(self.health.values()),
            group_db._FINGERPRINT: [(self.fingerprint,)],
        }
        return Cursor(answers.get(sql, []))

    def transaction(self):
        return nullcontext()

    def cursor(self):
        return Cursor([], connection=self)

    def close(self):
        pass


class GroupDatabaseTest(unittest.TestCase):
    def test_the_database_gives_the_same_listings_as_the_csv(self):
        database = FakePostgres()
        with closing(create_database()) as from_csv:
            expected = {listing["listing_id"]: listing for listing in load_listings(from_csv)}
        connection, fingerprint = load(database)
        with closing(connection):
            loaded = {listing["listing_id"]: listing for listing in load_listings(connection)}

        self.assertEqual(fingerprint, "first")
        self.assertEqual(loaded.keys(), expected.keys())
        for listing_id, listing in loaded.items():
            # enriched_at is not used; coord_error_m keeps two decimals and "~500" is stored as 500,
            # which the agent reads the same way.
            for field in set(listing) - {"enriched_at", "coord_error_m"}:
                self.assertEqual(listing[field], expected[listing_id][field], (listing_id, field))
            error, csv_error = coordinate_error_m(listing), coordinate_error_m(expected[listing_id])
            self.assertTrue(error == csv_error or abs(error - csv_error) < 0.01, listing_id)
        self.assertEqual(loaded["24611200"]["commutes"]["Faculty of Law"]["mode"], "transit_google")

    def test_walking_is_used_only_when_strictly_faster(self):
        database = FakePostgres()
        listing_id = database.listings[0]["listing_id"]
        database.commutes = [
            (listing_id, "Faculty of Law", "transit", "onemap", Decimal("20.00")),
            (listing_id, "Faculty of Law", "walk", "onemap", Decimal("20.00")),
            (listing_id, "Faculty of Science", "walk", "onemap", Decimal("12.00")),
            (listing_id, "Faculty of Science", "transit", "onemap", Decimal("18.00")),
        ]
        connection, _ = load(database)
        with closing(connection):
            (listing,) = [row for row in load_listings(connection) if row["listing_id"] == listing_id]

        self.assertEqual(listing["commutes"]["Faculty of Law"], {"minutes": 20.0, "mode": "transit"})
        self.assertEqual(listing["commutes"]["Faculty of Science"], {"minutes": 12.0, "mode": "walk"})

    def test_the_copy_is_rebuilt_only_when_the_data_changes(self):
        database = FakePostgres()
        listings = LiveListings(lambda: database, every=3600)
        first = listings.connection

        self.assertFalse(listings.refresh())  # not due yet
        self.assertFalse(listings.refresh(force=True))  # due, but nothing changed
        self.assertIs(listings.connection, first)
        database.fingerprint = "second"
        database.listings = database.listings[:10]
        self.assertTrue(listings.refresh(force=True))
        self.assertEqual(len(load_listings(listings)), 10)
        # A connection the server closed while idle is replaced once, without an error.
        database.drops, database.fingerprint, database.listings = 1, "third", database.listings[:5]
        self.assertTrue(listings.refresh(force=True))
        self.assertEqual(len(load_listings(listings)), 5)
        # An unreachable database leaves the loaded copy in use and is left alone for a while.
        database.fail, database.fingerprint = True, "fourth"
        with self.assertLogs(level="WARNING"):
            self.assertFalse(listings.refresh(force=True))
        database.fail = False
        with self.assertLogs(level="WARNING"):
            self.assertFalse(listings.refresh(force=True))
        self.assertEqual(len(load_listings(listings)), 5)
        listings.close()

    def test_link_checks_are_kept_in_the_database_and_loaded_again(self):
        from tools import validate_ranked_listings

        database = FakePostgres()
        listings = LiveListings(lambda: database)
        listing = load_listings(listings)[0]
        checked = validate_ranked_listings(
            listings, [{"listing": listing}], lambda listing_id, url: {"status": "active", "final_url": url, "http_status": 200}
        )

        self.assertEqual(checked["summary"]["active_count"], 1)
        self.assertEqual(database.health[listing["listing_id"]][1], "active")
        # A new process starts from the saved check instead of opening the link again.
        again = LiveListings(lambda: database)
        never = lambda *_: self.fail("the link was checked again")
        self.assertEqual(validate_ranked_listings(again, [{"listing": listing}], never)["summary"]["active_count"], 1)
        listings.close()
        again.close()


class CommuteTablesTest(unittest.TestCase):
    def test_import_then_export_gives_the_same_csv(self):
        database = FakePostgres()
        imported = import_commutes(database)
        destinations, _, commutes = (rows for _, rows in database.written)
        names = {row[0]: row[2] for row in destinations}
        exported = [
            (listing_id, names[destination], minutes and Decimal(str(minutes)), travel_mode, provider, day, clock)
            for listing_id, destination, travel_mode, minutes, provider, day, clock in commutes
        ]
        database.execute = lambda sql, params=(): Cursor(exported)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "commute_faculty.csv"
            export_commutes(database, path)
            with path.open(encoding="utf-8", newline="") as file:
                again = {(row["listing_id"], row["faculty"]): row for row in csv.DictReader(file)}
        with COMMUTE_DATA.open(encoding="utf-8-sig", newline="") as file:
            original = {(row["listing_id"], row["faculty"]): row for row in csv.DictReader(file)}

        self.assertEqual(imported, len(original))
        self.assertEqual(again, original)
        # Faculty places come from faculties.py, codes included, under the ids the seed script uses.
        self.assertEqual({row[1] for row in destinations}, {faculty["code"] for faculty in FACULTIES})
        self.assertIn(("soc_default", "SOC"), {row[:2] for row in destinations})
        google = next(row for row in commutes if row[0] == "24611200")
        self.assertEqual((google[2], google[4], google[6]), ("transit", "google", None))
        self.assertIsInstance(next(row for row in commutes if row[6])[6], time)

    def test_a_run_does_not_replace_the_csv_with_a_smaller_database(self):
        database = FakePostgres()
        with COMMUTE_DATA.open(encoding="utf-8-sig", newline="") as file:
            in_file = sum(1 for _ in csv.DictReader(file))

        database.execute = lambda sql, params=(): Cursor([(0,)])
        with self.assertRaises(SystemExit):
            _check_database_is_current(database)
        database.execute = lambda sql, params=(): Cursor([(in_file,)])
        _check_database_is_current(database)


if __name__ == "__main__":
    unittest.main()
