import unittest
from contextlib import closing
from datetime import date
from unittest.mock import patch

from mock_db import create_mock_database
from models import SearchPreferences
from tools import (
    analyze_relaxations,
    extract_restrictions,
    load_listings,
    rank_listings,
    refresh_mrt_walk_data,
    search_listings,
)


class ToolsTest(unittest.TestCase):
    def test_uses_ten_minutes_for_a_soft_mrt_preference(self):
        preferences = SearchPreferences(
            max_price_sgd=1_500,
            ranking_priority="mrt",
        )
        with closing(create_mock_database()) as connection:
            by_id = {
                listing["listing_id"]: listing
                for listing in load_listings(connection)
            }
            ranking = rank_listings([by_id["S001"], by_id["S010"]], preferences)

        self.assertEqual(
            [item["listing"]["listing_id"] for item in ranking],
            ["S010", "S001"],
        )
        self.assertEqual([item["rank_value"] for item in ranking], [0.536, 0.73])
        self.assertEqual(ranking[0]["factors"]["mrt"]["ratio"], 0.4)
        self.assertEqual(ranking[0]["factors"]["mrt"]["weight"], 0.7)

    def test_sqlite_search_and_restriction_extraction(self):
        with closing(create_mock_database()) as connection:
            listings = load_listings(connection)
            preferences = SearchPreferences(
                max_price_sgd=1_300,
                room_type=" common room ",
                district_code="d05",
                max_mrt_minutes=10,
                verified_only=True,
            )
            matches = search_listings(connection, preferences)
            ranking = rank_listings(matches, preferences)

            self.assertEqual(len(listings), 12)
            self.assertEqual([row["listing_id"] for row in matches], ["S001", "S010"])
            self.assertEqual(
                [item["listing"]["listing_id"] for item in ranking],
                ["S010", "S001"],
            )
            self.assertEqual([item["rank_value"] for item in ranking], [0.692, 0.812])
            self.assertEqual(ranking[0]["factors"]["mrt"]["weight"], 0.5)
            self.assertEqual(
                [
                    row["listing_id"]
                    for row in search_listings(connection, preferences, ["S001"])
                ],
                ["S010"],
            )
            move_in_and_cooking = preferences.model_copy(
                update={
                    "move_in_date": date(2026, 9, 20),
                    "cooking_required": True,
                }
            )
            self.assertEqual(
                [
                    row["listing_id"]
                    for row in search_listings(connection, move_in_and_cooking)
                ],
                ["S001"],
            )

            cheaper = preferences.model_copy(update={"max_price_sgd": 1_100})
            self.assertEqual(
                analyze_relaxations(connection, cheaper, ["S001"]),
                [],
            )

            matches[0]["mrt_walk_minutes"] = 1
            recalculated = rank_listings(matches, preferences)
            by_listing_id = {
                item["listing"]["listing_id"]: item for item in recalculated
            }
            self.assertEqual(by_listing_id["S001"]["factors"]["mrt"]["ratio"], 0.1)

            by_id = {row["listing_id"]: row for row in listings}
            self.assertEqual(
                extract_restrictions(by_id["S002"]),
                {
                    "cooking": "not_allowed",
                    "owner_staying": "yes",
                    "tenant_gender": "unknown",
                    "visitors": "unknown",
                    "smoking": "unknown",
                },
            )
            self.assertEqual(extract_restrictions(by_id["S009"])["cooking"], "unknown")

        with self.assertRaises(ValueError):
            SearchPreferences(max_price_sgd=0)

    def test_mrt_walk_refresh_is_persisted_and_reused(self):
        with closing(create_mock_database()) as connection:
            pending = connection.execute(
                """
                SELECT count(*) FROM listings
                WHERE listing_status_code = 'ACT'
                  AND address IS NOT NULL AND trim(address) <> ''
                  AND mrt_station IS NOT NULL AND trim(mrt_station) <> ''
                """
            ).fetchone()[0]
            route = {
                "mrt_station": "Test MRT",
                "mrt_walk_distance_m": 886,
                "mrt_walk_seconds": 639,
                "mrt_walk_minutes": 11,
            }

            with (
                patch("tools.load_token", return_value="fresh-token") as load_token,
                patch("tools.calculate_mrt_walk", return_value=route) as calculate,
            ):
                first = refresh_mrt_walk_data(connection)
                second = refresh_mrt_walk_data(connection)

            self.assertEqual(len(first["updated"]), pending)
            self.assertEqual(first["not_found"], [])
            self.assertEqual(second, {"updated": [], "not_found": []})
            load_token.assert_called_once_with()
            self.assertEqual(calculate.call_count, pending)

            preferences = SearchPreferences(
                max_price_sgd=1_300,
                room_type="Common Room",
                district_code="D05",
                max_mrt_minutes=10,
                verified_only=True,
            )
            self.assertEqual(search_listings(connection, preferences), [])


if __name__ == "__main__":
    unittest.main()
