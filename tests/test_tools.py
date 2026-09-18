import unittest
from contextlib import closing
from datetime import date
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from mock_db import create_database, create_mock_database
from models import SearchPreferences
from response import render_response
from tools import (
    analyze_relaxations,
    check_listing_url,
    extract_restrictions,
    load_listings,
    rank_listings,
    refresh_mrt_walk_data,
    search_listings,
    validate_ranked_listings,
)


class ToolsTest(unittest.TestCase):
    def test_imports_the_v2_listings(self):
        with closing(create_database()) as connection:
            listings = load_listings(connection)
            main_fields = connection.execute("PRAGMA table_info(listings)").fetchall()
        by_id = {listing["listing_id"]: listing for listing in listings}

        self.assertEqual(len(listings), 519)
        self.assertEqual(len(main_fields), 51)
        self.assertIn("availability_status", listings[0])
        self.assertEqual(listings[0]["live_status"], "unknown")
        self.assertTrue(all(listing["district"] for listing in listings))
        # V2 labels are stored as the V1 values that search filters understand.
        self.assertLessEqual({listing["cooking_policy"] for listing in listings}, {"allowed", "light_only", "not_allowed", "unknown"})
        self.assertLessEqual({listing["pets_policy"] for listing in listings}, {"allowed", "not_allowed", "unknown"})
        # The rechecked rent is used when V2 has one; the card rent is kept.
        self.assertEqual((by_id["24842419"]["rent_monthly_sgd"], by_id["24842419"]["rent_monthly_sgd_card"]), (5800, 5900))
        self.assertEqual((by_id["500253628"]["rent_monthly_sgd"], by_id["500253628"]["rent_monthly_sgd_now"]), (1850, None))
        # The 80 sqft check runs on V2 areas; 7.43 sqm is an 80 sqft room.
        self.assertIn("area_outside_review_range", by_id["25107881"]["review_flags"])
        self.assertNotIn("area_outside_review_range", by_id["25558367"]["review_flags"])
        # V2.3 adds coordinates and nearby counts; food_rank is derived at load time.
        self.assertEqual(by_id["24842419"]["coord_source"], "onemap_postcode")
        self.assertTrue(all(listing["poi_fnb_1km"] is not None for listing in listings))
        # food_rank averages the F&B and hawker positions: 0 is the most choice, 1 the least.
        self.assertLess(by_id["24970286"]["food_rank"], 0.05)   # 1282 F&B, 8 hawker centres
        self.assertGreater(by_id["500249175"]["food_rank"], 0.95)  # 3 F&B, no hawker centre

    def test_amenities_priority_ranks_by_nearby_food(self):
        preferences = SearchPreferences(max_price_sgd=5000, ranking_priority="amenities")
        with closing(create_database()) as connection:
            listings = search_listings(connection, preferences)
            ranked = rank_listings(listings, preferences)
            balanced = rank_listings(listings, preferences.model_copy(update={"ranking_priority": "balanced"}))

        self.assertEqual(ranked[0]["factors"]["food"]["weight"], 0.7)
        self.assertEqual(ranked[0]["factors"]["price"]["weight"], 0.3)
        # The top three all sit in the busiest tenth for nearby food.
        self.assertTrue(all(item["listing"]["food_rank"] <= 0.1 for item in ranked[:3]))
        self.assertNotEqual(
            [item["listing"]["listing_id"] for item in ranked[:3]],
            [item["listing"]["listing_id"] for item in balanced[:3]],
        )
        self.assertNotIn("food", balanced[0]["factors"])

    def test_url_checks_compare_the_final_listing_id(self):
        class Response:
            status = 200

            def __init__(self, final_url):
                self.final_url = final_url

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def geturl(self):
                return self.final_url

        source = "https://www.propertyguru.com.sg/listing/example-500253628"
        with patch("tools.urlopen", return_value=Response(source)):
            self.assertEqual(
                check_listing_url("500253628", source)["status"],
                "active",
            )
        with patch(
            "tools.urlopen",
            return_value=Response(
                "https://www.propertyguru.com.sg/listing/replacement-500999999"
            ),
        ):
            self.assertEqual(
                check_listing_url("500253628", source)["status"],
                "inactive",
            )

        for status_code, expected in ((404, "inactive"), (429, "unknown")):
            with self.subTest(status_code=status_code), patch(
                "tools.urlopen",
                side_effect=HTTPError(source, status_code, "error", {}, None),
            ):
                result = check_listing_url("500253628", source)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["error_reason"], f"http_{status_code}")

        with patch("tools.urlopen", side_effect=URLError("offline")):
            result = check_listing_url("500253628", source)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["error_reason"], "network_error")

    def test_live_validation_drops_redirected_listings(self):
        with closing(create_mock_database()) as connection:
            preferences = SearchPreferences(
                max_price_sgd=1_300,
                room_type="common_room",
                district_code="D05",
            )
            ranked = rank_listings(search_listings(connection, preferences), preferences)
            connection.execute(
                "DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')"
            )

            def checker(listing_id, url):
                return {
                    "status": "inactive" if listing_id == "S010" else "active",
                    "final_url": url,
                    "http_status": 200,
                }

            validated = validate_ranked_listings(connection, ranked, checker)["ranked_listings"]

        self.assertEqual(
            [item["listing"]["listing_id"] for item in validated],
            ["S001"],
        )

    def test_live_validation_keeps_unknown_in_rank_order_and_explains_it(self):
        with closing(create_mock_database()) as connection:
            preferences = SearchPreferences(
                max_price_sgd=1_300,
                room_type="common_room",
                district_code="D05",
            )
            ranked = rank_listings(search_listings(connection, preferences), preferences)
            connection.execute(
                "DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')"
            )

            def checker(listing_id, url):
                return {
                    "status": "unknown" if listing_id == "S001" else "active",
                    "final_url": None if listing_id == "S001" else url,
                    "http_status": None if listing_id == "S001" else 200,
                    "error_reason": "network_error" if listing_id == "S001" else None,
                }

            validation = validate_ranked_listings(connection, ranked, checker)
            validated = validation["ranked_listings"]
            response = render_response(validated, check_summary=validation["summary"])

        self.assertEqual(
            [item["listing"]["listing_id"] for item in validated],
            ["S001", "S010"],
        )
        self.assertEqual(
            validated[0]["listing"]["live_error_reason"],
            "network_error",
        )
        self.assertIn("检查时发生网络错误", response)
        self.assertIn("这不表示房源已下架", response)

    def test_live_validation_refills_after_the_first_ten_are_inactive(self):
        with closing(create_mock_database()) as connection:
            ranked = [{"listing": listing} for listing in load_listings(connection)]
            connection.execute("DELETE FROM listing_health")
            later_ids = [item["listing"]["listing_id"] for item in ranked[10:]]
            checked_ids = []

            def checker(listing_id, url):
                checked_ids.append(listing_id)
                return {
                    "status": "active" if listing_id in later_ids else "inactive",
                    "final_url": url,
                    "http_status": 200 if listing_id in later_ids else 404,
                }

            validation = validate_ranked_listings(connection, ranked, checker, result_limit=2)

        self.assertEqual(
            [item["listing"]["listing_id"] for item in validation["ranked_listings"]],
            later_ids,
        )
        self.assertEqual(len(checked_ids), 12)
        self.assertEqual(validation["summary"], {
            "database_match_count": 12,
            "checked_count": 12,
            "active_count": 2,
            "unknown_count": 0,
            "inactive_count": 10,
            "unchecked_count": 0,
        })

    def test_live_validation_stops_when_enough_unknown_or_active_results_exist(self):
        with closing(create_mock_database()) as connection:
            ranked = [{"listing": listing} for listing in load_listings(connection)]
            connection.execute("DELETE FROM listing_health")
            checker = Mock(side_effect=[
                {"status": "unknown", "error_reason": "timeout"},
                {"status": "active"},
            ])
            validation = validate_ranked_listings(connection, ranked, checker, result_limit=2)

        self.assertEqual(checker.call_count, 2)
        self.assertEqual(
            [item["listing"]["listing_id"] for item in validation["ranked_listings"]],
            [item["listing"]["listing_id"] for item in ranked[:2]],
        )
        self.assertEqual(validation["summary"]["unchecked_count"], 10)
        self.assertEqual(validation["summary"]["unknown_count"], 1)

    def test_live_validation_reports_unchecked_candidates_at_the_cap(self):
        with closing(create_mock_database()) as connection:
            ranked = [{"listing": listing} for listing in load_listings(connection)]
            connection.execute("DELETE FROM listing_health")
            checker = Mock(return_value={"status": "inactive"})
            validation = validate_ranked_listings(
                connection, ranked, checker, candidate_limit=3, result_limit=3
            )
            response = render_response([], check_summary=validation["summary"])
            english = render_response([], check_summary=validation["summary"], language="en")

        self.assertEqual(checker.call_count, 3)
        self.assertEqual(validation["ranked_listings"], [])
        self.assertEqual(validation["summary"]["unchecked_count"], 9)
        self.assertIn("另有 9 套尚未检查", response)
        self.assertIn("Another 9 candidates remain unchecked", english)

    def test_relaxation_counts_only_displayable_checked_candidates(self):
        preferences = SearchPreferences(max_price_sgd=1_200, room_type="common_room", district_code="D05")
        with closing(create_mock_database()) as connection:
            connection.execute("DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')")

            def checker(listing_id, url):
                return {
                    "status": "unknown" if listing_id == "S010" else "inactive",
                    "error_reason": "http_403" if listing_id == "S010" else "http_404",
                }

            suggestions = analyze_relaxations(connection, preferences, checker=checker)
            response = render_response(relaxations=suggestions)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["match_count"], 1)
        self.assertEqual(suggestions[0]["check_summary"]["database_match_count"], 2)
        self.assertEqual(suggestions[0]["check_summary"]["active_count"], 0)
        self.assertEqual(suggestions[0]["check_summary"]["unknown_count"], 1)
        self.assertEqual(suggestions[0]["check_summary"]["inactive_count"], 1)
        self.assertIn("本次校验后可展示 1 套", response)
        self.assertIn("状态无法确认 1 套", response)
        self.assertNotIn("预计可找到 2", response)

    def test_relaxations_do_not_offer_candidates_whose_links_are_all_inactive(self):
        preferences = SearchPreferences(max_price_sgd=1_100, room_type="common_room", district_code="D05")
        with closing(create_mock_database()) as connection:
            connection.execute("DELETE FROM listing_health WHERE listing_id = 'S001'")
            suggestions = analyze_relaxations(
                connection, preferences, checker=lambda *_: {"status": "inactive"}
            )

        self.assertEqual(suggestions, [])

    def test_only_keeps_small_area_review_warnings(self):
        with closing(create_mock_database()) as connection:
            connection.execute(
                "UPDATE listings SET area_sqm = ? WHERE listing_id = ?",
                (930.42, "S010"),
            )
            connection.execute(
                "UPDATE listing_metadata SET review_flags = ? WHERE listing_id = ?",
                ('["area_outside_review_range", "tenant_count_scope_unconfirmed"]', "S010"),
            )
            connection.execute(
                "UPDATE listings SET area_sqm = ? WHERE listing_id = ?",
                (4.09, "S009"),
            )
            connection.execute(
                "UPDATE listing_metadata SET review_flags = ? WHERE listing_id = ?",
                ('["area_outside_review_range"]', "S009"),
            )
            by_id = {
                listing["listing_id"]: listing
                for listing in load_listings(connection)
            }

        self.assertEqual(by_id["S010"]["review_flags"], [])
        self.assertEqual(
            by_id["S009"]["review_flags"],
            ["area_outside_review_range"],
        )

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

        self.assertEqual(by_id["S010"]["review_flags"], [])
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
                SELECT count(*) FROM agent_listings
                WHERE live_status <> 'inactive'
                  AND address IS NOT NULL AND trim(address) <> ''
                  AND mrt_station <> 'unknown' AND trim(mrt_station) <> ''
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
            )
            self.assertEqual(search_listings(connection, preferences), [])


if __name__ == "__main__":
    unittest.main()
