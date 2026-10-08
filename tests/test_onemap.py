import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from time import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import config
import onemap
from onemap import OneMapError, OneMapNotFound, calculate_mrt_walk, get_token, load_token


class FakeOpener:
    def __init__(self):
        self.calls = []
        self.responses = iter(
            [
                {"results": [{"LATITUDE": "1.3000", "LONGITUDE": "103.7700"}]},
                {"results": [{"LATITUDE": "1.3100", "LONGITUDE": "103.7800"}]},
                {
                    "route_summary": {
                        "total_time": 361,
                        "total_distance": 512.4,
                    }
                },
            ]
        )

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        return io.BytesIO(json.dumps(next(self.responses)).encode())


class OneMapTest(unittest.TestCase):
    def test_calculate_mrt_walk(self):
        opener = FakeOpener()

        result = calculate_mrt_walk(
            "101 Clementi Avenue",
            "Clementi MRT Station",
            "test-token",
            opener=opener,
        )

        self.assertEqual(
            result,
            {
                "mrt_station": "Clementi MRT Station",
                "mrt_walk_distance_m": 512,
                "mrt_walk_seconds": 361,
                "mrt_walk_minutes": 7,
            },
        )
        self.assertEqual(len(opener.calls), 3)
        self.assertTrue(
            all(call[0].get_header("Authorization") == "test-token" for call in opener.calls)
        )
        route_query = parse_qs(urlparse(opener.calls[-1][0].full_url).query)
        self.assertEqual(route_query["routeType"], ["walk"])



class FakeTokenOpener:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload or {
            "access_token": "fresh-token",
            "expiry_timestamp": str(int(time()) + 3 * 24 * 3600),
        }

    def __call__(self, request, timeout):
        self.calls.append(request)
        return io.BytesIO(json.dumps(self.payload).encode())


class GetTokenTest(unittest.TestCase):
    def test_posts_credentials_and_returns_token(self):
        opener = FakeTokenOpener()

        result = get_token("user@example.com", "secret", opener=opener)

        self.assertEqual(result["access_token"], "fresh-token")
        self.assertIsInstance(result["expiry_timestamp"], int)

        request = opener.calls[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.full_url, "https://www.onemap.gov.sg/api/auth/post/getToken"
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data),
            {"email": "user@example.com", "password": "secret"},
        )

    def test_missing_token_in_response_raises(self):
        opener = FakeTokenOpener({"error": "bad credentials"})

        with self.assertRaises(OneMapError):
            get_token("user@example.com", "secret", opener=opener)


class LoadTokenTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.cache = Path(self._temp.name) / "token.json"
        # Isolate from the developer's real .env / shell, which would otherwise
        # hand load_token a genuine ONEMAP_TOKEN and defeat these tests.
        credentials = patch.dict(
            os.environ,
            {"ONEMAP_EMAIL": "user@example.com", "ONEMAP_PASSWORD": "secret"},
        )
        credentials.start()
        self.addCleanup(credentials.stop)
        os.environ.pop("ONEMAP_TOKEN", None)
        dotenv = patch.object(config, "_dotenv", return_value={})
        dotenv.start()
        self.addCleanup(dotenv.stop)

    def test_fetches_and_caches(self):
        opener = FakeTokenOpener()

        token = load_token(cache_path=self.cache, opener=opener)

        self.assertEqual(token, "fresh-token")
        self.assertEqual(json.loads(self.cache.read_text())["access_token"], "fresh-token")

    def test_reuses_valid_cache(self):
        self.cache.write_text(
            json.dumps(
                {"access_token": "cached-token", "expiry_timestamp": int(time()) + 3600}
            )
        )
        opener = FakeTokenOpener()

        self.assertEqual(load_token(cache_path=self.cache, opener=opener), "cached-token")
        self.assertEqual(opener.calls, [])

    def test_refreshes_expired_cache(self):
        self.cache.write_text(
            json.dumps(
                {"access_token": "stale-token", "expiry_timestamp": int(time()) - 1}
            )
        )
        opener = FakeTokenOpener()

        self.assertEqual(load_token(cache_path=self.cache, opener=opener), "fresh-token")
        self.assertEqual(len(opener.calls), 1)



class ErrorReportingTest(unittest.TestCase):
    def test_http_error_names_status_and_body(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"Invalid token"}')
            )

        with self.assertRaises(OneMapError) as caught:
            calculate_mrt_walk("somewhere", "some MRT", "stale-token", opener=opener)

        message = str(caught.exception)
        self.assertIn("401", message)
        self.assertIn("expired", message)
        self.assertIn("Invalid token", message)



class NotFoundTest(unittest.TestCase):
    def test_empty_results_is_not_an_api_failure(self):
        def opener(request, timeout):
            return io.BytesIO(json.dumps({"found": 0, "results": []}).encode())

        with self.assertRaises(OneMapNotFound) as caught:
            calculate_mrt_walk("nowhere road", "some MRT", "good-token", opener=opener)

        self.assertIn("no match", str(caught.exception))
        self.assertIn("succeeded", str(caught.exception))
        # Callers that only know about OneMapError still catch it.
        self.assertIsInstance(caught.exception, OneMapError)


if __name__ == "__main__":
    unittest.main()
