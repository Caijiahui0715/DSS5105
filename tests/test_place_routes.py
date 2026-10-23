import time
import unittest
from datetime import datetime
from unittest.mock import patch

import place_routes
from models import Destination
from onemap import OneMapError
from place_routes import RateLimiter, onemap_trip


class PlaceRoutesTest(unittest.TestCase):
    def test_calls_are_spaced_by_the_shared_rate(self):
        limiter = RateLimiter(600)  # one call every 0.1 s
        started = time.monotonic()
        for _ in range(4):
            limiter.wait()
        self.assertGreaterEqual(time.monotonic() - started, 0.29)

    def test_too_many_requests_waits_and_asks_again_and_other_errors_do_not(self):
        calls = []

        def busy_once(*args):
            calls.append(args)
            if len(calls) == 1:
                raise OneMapError("OneMap /api/public/routingsvc/route failed: HTTP 429. Too many requests")
            return 17

        def broken(*args):
            calls.append(args)
            raise OneMapError("OneMap /api/public/routingsvc/route failed: HTTP 502.")

        with patch.object(place_routes, "LIMITER", RateLimiter(6000)), patch.object(place_routes, "_BACKOFF_SECONDS", 0.01):
            self.assertEqual(place_routes._call(busy_once, "a"), 17)
            self.assertEqual(len(calls), 2)
            calls.clear()
            with self.assertRaises(OneMapError):
                place_routes._call(broken, "a")
        self.assertEqual(len(calls), 1)

    def test_a_place_within_walking_distance_takes_the_faster_way(self):
        gym = Destination(query="Somewhere", latitude=1.3000, longitude=103.7700)
        near = {"latitude": 1.3050, "longitude": 103.7700}  # about 560 m
        far = {"latitude": 1.3500, "longitude": 103.7700}  # about 5.6 km
        walks = []
        with patch.object(place_routes, "LIMITER", RateLimiter(6000)), \
                patch.object(place_routes, "public_transport_minutes", lambda *args: 12), \
                patch.object(place_routes, "walking_minutes", lambda *args: walks.append(args) or 8):
            departure = datetime(2026, 10, 22, 8, 30)
            self.assertEqual(onemap_trip(near, gym, "token", departure), {"minutes": 8, "mode": "walk"})
            self.assertEqual(onemap_trip(far, gym, "token", departure), {"minutes": 12, "mode": "transit"})
        self.assertEqual(len(walks), 1)


if __name__ == "__main__":
    unittest.main()
