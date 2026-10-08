import csv
import io
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from build_commutes import WALK_CHECK_M, build, next_weekday_morning
from faculties import FACULTIES, find_faculty
from onemap import OneMapError, public_transport_minutes, walking_minutes
from tools import location_distance_m

DEPARTURE = datetime(2026, 10, 12, 8, 30)
BUSINESS = find_faculty("商学院")
# Far from every faculty, so only public transport is asked.
FAR = {"listing_id": "A", "latitude": 1.35, "longitude": 103.94}
# Beside the Business School: faculties within 1.5 km are also walked.
NEAR = {"listing_id": "N", "latitude": 1.2930, "longitude": 103.7745}


def near_faculties(listing):
    return [
        faculty["name"]
        for faculty in FACULTIES
        if location_distance_m(listing, SimpleNamespace(latitude=faculty["latitude"], longitude=faculty["longitude"])) <= WALK_CHECK_M
    ]


def never(*_):
    raise AssertionError("OneMap was asked again")


def read(path):
    with path.open(encoding="utf-8", newline="") as file:
        return {(row["listing_id"], row["faculty"]): row for row in csv.DictReader(file)}


class CommuteDataTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "commute_faculty.csv"

    def test_a_stopped_run_keeps_its_routes_and_resumes(self):
        calls = []

        def route(start, end, when):
            calls.append((start, end, when))
            if len(calls) == 3:
                raise OneMapError("still timed out after three tries")
            return None if len(calls) == 2 else 40

        located_nowhere = {"listing_id": "B", "latitude": None, "longitude": None}
        with self.assertRaises(OneMapError):
            build([FAR, located_nowhere], self.path, DEPARTURE, route, never)
        self.assertEqual(len(read(self.path)), 2)
        asked = build([FAR, located_nowhere], self.path, DEPARTURE, lambda *_: 45, never)
        rows = read(self.path)

        self.assertEqual(calls[0], ((1.35, 103.94), (FACULTIES[0]["latitude"], FACULTIES[0]["longitude"]), DEPARTURE))
        # The two saved routes are not asked again; B has no coordinates.
        self.assertEqual(asked, {"transit": len(FACULTIES) - 2, "walk": 0, "walk_faster": 0})
        self.assertEqual(len(rows), len(FACULTIES))
        self.assertEqual(
            rows["A", FACULTIES[0]["name"]],
            {"listing_id": "A", "faculty": FACULTIES[0]["name"], "minutes": "40", "mode": "transit", "departure": "2026-10-12 08:30"},
        )
        # No route is recorded as empty, not as zero minutes.
        self.assertEqual((rows["A", FACULTIES[1]["name"]]["minutes"], rows["A", FACULTIES[1]["name"]]["mode"]), ("", ""))
        self.assertEqual(rows["A", FACULTIES[2]["name"]]["minutes"], "45")

    def test_within_1_5_km_the_faster_of_walking_and_transit_is_kept(self):
        near = near_faculties(NEAR)
        walked = []

        def walk(start, end):
            walked.append(end)
            # Walking beats the 20-minute bus only to the Business School next door.
            return 6 if end == (BUSINESS["latitude"], BUSINESS["longitude"]) else 30

        asked = build([NEAR], self.path, DEPARTURE, lambda *_: 20, walk)
        rows = read(self.path)
        far = next(faculty["name"] for faculty in FACULTIES if faculty["name"] not in near)
        other_near = next(name for name in near if name != BUSINESS["name"])

        self.assertTrue(1 < len(near) < len(FACULTIES))
        self.assertEqual(asked, {"transit": len(FACULTIES), "walk": len(near), "walk_faster": 1})
        self.assertEqual((rows["N", BUSINESS["name"]]["minutes"], rows["N", BUSINESS["name"]]["mode"]), ("6", "walk"))
        self.assertEqual((rows["N", other_near]["minutes"], rows["N", other_near]["mode"]), ("20", "transit"))
        self.assertEqual((rows["N", far]["minutes"], rows["N", far]["mode"]), ("20", "transit"))
        # A second run has nothing left to ask.
        self.assertEqual(build([NEAR], self.path, DEPARTURE, never, never), {"transit": 0, "walk": 0, "walk_faster": 0})

    def test_a_file_from_before_walking_checks_gains_them(self):
        near = near_faculties(NEAR)
        far = next(faculty["name"] for faculty in FACULTIES if faculty["name"] not in near)
        self.path.write_text(
            "listing_id,faculty,minutes,departure\n" + "".join(f"N,{faculty['name']},20,2026-10-07 08:30\n" for faculty in FACULTIES),
            encoding="utf-8",
        )

        asked = build([NEAR], self.path, DEPARTURE, never, lambda start, end: 6)
        rows = read(self.path)

        self.assertEqual(asked, {"transit": 0, "walk": len(near), "walk_faster": len(near)})
        self.assertEqual((rows["N", BUSINESS["name"]]["minutes"], rows["N", BUSINESS["name"]]["mode"]), ("6", "walk"))
        self.assertEqual(
            (rows["N", far]["minutes"], rows["N", far]["mode"], rows["N", far]["departure"]),
            ("20", "transit", "2026-10-07 08:30"),
        )

    def test_listings_with_unreliable_transit_routes_are_only_walked(self):
        normanton = {"listing_id": "24611200", "latitude": 1.286309196068188, "longitude": 103.7927028286491}

        asked = build([normanton], self.path, DEPARTURE, never, lambda start, end: 22)
        rows = read(self.path)

        # Only the Faculty of Dentistry is within 1.5 km; every other faculty has no data.
        self.assertEqual(near_faculties(normanton), ["Faculty of Dentistry"])
        self.assertEqual(asked, {"transit": 0, "walk": 1, "walk_faster": 1})
        self.assertEqual((rows["24611200", "Faculty of Dentistry"]["minutes"], rows["24611200", "Faculty of Dentistry"]["mode"]), ("22", "walk"))
        self.assertTrue(all(row["minutes"] == "" for key, row in rows.items() if key[1] != "Faculty of Dentistry"))

    def test_the_default_departure_is_the_next_weekday_morning(self):
        self.assertEqual(next_weekday_morning(date(2026, 10, 9)), datetime(2026, 10, 12, 8, 30))
        self.assertEqual(next_weekday_morning(date(2026, 10, 6)), datetime(2026, 10, 7, 8, 30))


class OneMapRouteTest(unittest.TestCase):
    start, end = (1.3, 103.8), (1.29, 103.77)

    def test_public_transport_minutes_take_the_fastest_trip(self):
        sent = []

        def opener(request, timeout):
            sent.append(request.full_url)
            return io.BytesIO(json.dumps({"plan": {"itineraries": [{"duration": 1500}, {"duration": 1321}]}}).encode())

        self.assertEqual(public_transport_minutes(self.start, self.end, "token", DEPARTURE, opener=opener), 23)
        for part in ("routeType=pt", "mode=TRANSIT", "date=10-12-2026", "time=08%3A30%3A00", "start=1.3%2C103.8"):
            self.assertIn(part, sent[0])

    def test_walking_minutes(self):
        sent = []

        def opener(request, timeout):
            sent.append(request.full_url)
            return io.BytesIO(b'{"route_summary": {"total_time": 601, "total_distance": 700}}')

        self.assertEqual(walking_minutes(self.start, self.end, "token", opener=opener), 11)
        self.assertIn("routeType=walk", sent[0])

    def test_slow_answers_are_asked_again_then_raised(self):
        attempts = []

        def slow_twice(request, timeout):
            attempts.append(timeout)
            if len(attempts) < 3:
                raise TimeoutError("timed out")
            return io.BytesIO(b'{"route_summary": {"total_time": 601}}')

        def always_slow(request, timeout):
            raise TimeoutError("timed out")

        with patch("onemap.sleep") as pause:
            self.assertEqual(walking_minutes(self.start, self.end, "token", opener=slow_twice), 11)
        self.assertEqual(attempts, [30, 30, 30])
        self.assertEqual([call.args[0] for call in pause.call_args_list], [4, 8])
        # Still slow after three tries: an error the script stops on, never a saved "no route".
        with patch("onemap.sleep"), self.assertRaises(OneMapError):
            public_transport_minutes(self.start, self.end, "token", DEPARTURE, opener=always_slow)

    def test_no_route_is_none_and_other_failures_are_raised(self):
        def no_route(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error": "No route found"}'))

        def refused(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"denied"))

        self.assertIsNone(walking_minutes(self.start, self.end, "token", opener=no_route))
        self.assertIsNone(public_transport_minutes(self.start, self.end, "token", DEPARTURE, opener=no_route))
        with self.assertRaises(OneMapError):
            public_transport_minutes(self.start, self.end, "token", DEPARTURE, opener=refused)


if __name__ == "__main__":
    unittest.main()
