import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from pydantic import ValidationError

from mock_db import create_database, create_mock_database
from models import SearchPreferences
from response import render_budget_check, render_budget_conversion, render_preference_changes, render_response
from tools import (
    analyze_relaxations,
    check_listing_url,
    commute_minutes,
    extract_restrictions,
    get_listings_by_ids,
    load_listings,
    mrt_minutes,
    rank_listings,
    refresh_mrt_walk_data,
    rent_percentile_sgd,
    search_listings,
    validate_ranked_listings,
)


class ToolsTest(unittest.TestCase):
    def test_imports_the_v2_listings(self):
        with closing(create_database()) as connection:
            listings = load_listings(connection)
        by_id = {listing["listing_id"]: listing for listing in listings}

        self.assertEqual(len(listings), 327)
        # The V2 columns with lease_term, derived ranks and commutes, metadata and link checks.
        self.assertEqual(len(listings[0]), 73)
        self.assertIn("availability_status", listings[0])
        self.assertEqual(listings[0]["live_status"], "unknown")
        self.assertTrue(all(listing["district"] for listing in listings))
        # V2 labels are stored as the V1 values that search filters understand.
        self.assertLessEqual({listing["cooking_policy"] for listing in listings}, {"allowed", "light_only", "not_allowed", "unknown"})
        self.assertLessEqual({listing["pets_policy"] for listing in listings}, {"allowed", "not_allowed", "unknown"})
        # The rechecked rent is used when V2 has one; the card rent is kept.
        self.assertEqual((by_id["25604246"]["rent_monthly_sgd"], by_id["25604246"]["rent_monthly_sgd_card"]), (5500, 5700))
        # Every current listing was rechecked; the fixture has none, so its card rent is used.
        self.assertTrue(all(listing["rent_monthly_sgd_now"] is not None for listing in listings))
        with closing(create_mock_database()) as connection:
            card_only = get_listings_by_ids(connection, ["S001"])[0]
        self.assertEqual((card_only["rent_monthly_sgd"], card_only["rent_monthly_sgd_now"]), (card_only["rent_monthly_sgd_card"], None))
        # The 80 sqft check runs on V2 areas; 7.43 sqm is an 80 sqft room.
        self.assertIn("area_outside_review_range", by_id["25107881"]["review_flags"])
        self.assertNotIn("area_outside_review_range", by_id["25558367"]["review_flags"])
        # V2.3 adds coordinates and nearby counts; food_rank is derived at load time.
        self.assertEqual(by_id["25558367"]["coord_source"], "onemap_postcode")
        # The lease term the advert states, kept as written; empty cells are NULL.
        terms = [listing["lease_term"] for listing in listings]
        self.assertEqual((terms.count("2 years"), terms.count("1 year"), terms.count(None)), (134, 27, 104))
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
        self.assertEqual(ranked[0]["factors"]["price"]["weight"], 0.15)
        self.assertEqual(ranked[0]["factors"]["mrt"]["weight"], 0.15)
        # The top three all sit in the busiest tenth for nearby food.
        self.assertTrue(all(item["listing"]["food_rank"] <= 0.1 for item in ranked[:3]))
        self.assertNotEqual(
            [item["listing"]["listing_id"] for item in ranked[:3]],
            [item["listing"]["listing_id"] for item in balanced[:3]],
        )
        self.assertNotIn("food", balanced[0]["factors"])

    def test_ranking_priority_keeps_up_to_three_names(self):
        self.assertEqual(SearchPreferences().ranking_priority, ())
        self.assertEqual(SearchPreferences(ranking_priority="balanced").ranking_priority, ())
        self.assertEqual(SearchPreferences(ranking_priority="space").ranking_priority, ("space",))
        self.assertEqual(
            SearchPreferences(ranking_priority=["space", "food_places", "space"]).ranking_priority,
            ("space", "food_places"),
        )
        with self.assertRaisesRegex(ValidationError, "ask the user which matter most"):
            SearchPreferences(ranking_priority=["space", "food_places", "mrt", "price"])

    def test_named_priorities_share_seventy_percent(self):
        listing = {
            "listing_id": "a", "rent_monthly_sgd": 1_000, "mrt_distance_m": 425,
            "mrt_operation_status": "operational", "space_rank": 0.2, "food_places_rank": 0.1,
        }
        cases = (
            ({"max_price_sgd": 2_000, "ranking_priority": "space"}, {"mrt": 0.15, "space": 0.7, "price": 0.15}),
            ({"ranking_priority": ["space", "food_places"]}, {"mrt": 0.3, "space": 0.35, "food_places": 0.35}),
            # The one other factor would get 30% against 23% for each named one, so all are equal.
            (
                {"max_price_sgd": 2_000, "ranking_priority": ["space", "food_places", "mrt"]},
                {"mrt": 0.25, "space": 0.25, "price": 0.25, "food_places": 0.25},
            ),
        )
        for preferences, weights in cases:
            with self.subTest(preferences=preferences):
                factors = rank_listings([listing], SearchPreferences(**preferences))[0]["factors"]
                self.assertEqual({name: factor["weight"] for name, factor in factors.items()}, weights)

    def test_an_added_priority_keeps_the_earlier_one_in_the_ranking(self):
        # 空间大 followed by 也想要餐厅多: space stays in the ranking instead of being replaced.
        preferences = SearchPreferences(max_price_sgd=3_000, ranking_priority=["space", "food_places"])
        with closing(create_database()) as connection:
            listings = search_listings(connection, preferences)

        def top_three(priorities, rank):
            ranked = rank_listings(listings, preferences.model_copy(update={"ranking_priority": priorities}))
            return sum(item["listing"][rank] for item in ranked[:3]) / 3

        # Search keeps only listings with data for every named priority.
        self.assertTrue(all(row["space_rank"] is not None and row["food_places_rank"] is not None for row in listings))
        # Ranks are 0 for the largest or busiest; both priorities beat ranking on either one alone.
        self.assertLess(top_three(("space", "food_places"), "space_rank"), top_three(("food_places",), "space_rank"))
        self.assertLess(top_three(("space", "food_places"), "food_places_rank"), top_three(("space",), "food_places_rank"))

    def test_priority_changes_show_what_is_kept(self):
        self.assertEqual(
            render_preference_changes(SearchPreferences(ranking_priority="space"), {"ranking_priority": ("space", "food_places")}),
            "已保存条件变更：排序偏好 空间大优先 → 空间大优先、餐饮点优先",
        )
        self.assertEqual(
            render_preference_changes(SearchPreferences(ranking_priority="space"), {"ranking_priority": ()}, "en"),
            "Saved preference changes: ranking priority more space → balanced",
        )

    def test_budget_conversion_shows_how_the_monthly_limit_was_reached(self):
        cny = {"original_amount": 300_000, "original_currency": "CNY", "rate_to_sgd": "0.19094", "rate_date": "2026-10-05", "amount_sgd": 57_282}
        # A monthly budget keeps the existing wording.
        self.assertEqual(
            render_budget_conversion({**cny, "original_amount": 5_000, "amount_sgd": 954}),
            "预算换算：5,000 CNY × 0.19094 = S$954（汇率日期 2026-10-05）。搜索使用 S$954 作为月租上限。",
        )
        self.assertEqual(
            render_budget_conversion({**cny, "months": 12, "monthly_sgd": 4_773}),
            "预算换算：12 个月共 300,000 CNY × 0.19094 = S$57,282（汇率日期 2026-10-05），÷ 12 = 每月 S$4,773。"
            "搜索使用 S$4,773 作为月租上限。",
        )
        sgd_year = {"original_amount": 60_000, "original_currency": "SGD", "amount_sgd": 60_000, "months": 12, "monthly_sgd": 5_000}
        self.assertEqual(
            render_budget_conversion(sgd_year, "en"),
            "Budget conversion: S$60,000 for 12 months, ÷ 12 = S$5,000 a month. The search used S$5,000 as the monthly rent limit.",
        )

    def test_a_monthly_limit_above_most_rents_is_flagged(self):
        with closing(create_mock_database()) as connection:
            # Eleven of the twelve fixture rents are at most S$3,800; the other is S$32,000.
            self.assertEqual(rent_percentile_sgd(connection, 0.9), 3_800)
        text = render_budget_check({"monthly_limit_sgd": 57_282, "rent_90th_percentile_sgd": 18_000})
        self.assertIn("每月 S$57,282 的上限高于数据中 90% 房源的月租（S$18,000）", text)
        self.assertIn("一年或整个租期的总预算", text)
        low = render_budget_check({"monthly_limit_sgd": 5, "lowest_rent_sgd": 528, "stated_budget": None}, "en")
        self.assertEqual(
            low,
            "Note: a monthly limit of S$5 is far below the cheapest rent in the data (S$528), so it was not used or "
            "saved. If a unit such as thousand is missing, tell me the correct amount.",
        )

    def test_balanced_ranking_weighs_mrt_walking_distance(self):
        preferences = SearchPreferences(max_price_sgd=1_100)
        with closing(create_mock_database()) as connection:
            ranked = rank_listings(search_listings(connection, preferences), preferences)

        # S002 (S$1,050, 430 m) beats the cheaper S004 (S$850, 940 m).
        self.assertEqual([item["listing"]["listing_id"] for item in ranked], ["S002", "S004"])
        self.assertEqual(ranked[0]["factors"]["mrt"], {"ratio": 0.506, "weight": 0.5})

    def test_missing_or_unopened_mrt_counts_as_a_ten_minute_walk(self):
        preferences = SearchPreferences(max_price_sgd=2_000)
        listings = [
            {"listing_id": "near", "rent_monthly_sgd": 1_000, "mrt_distance_m": 425, "mrt_operation_status": "operational"},
            {"listing_id": "none", "rent_monthly_sgd": 1_000, "mrt_distance_m": None, "mrt_operation_status": "unknown"},
            {"listing_id": "uc", "rent_monthly_sgd": 1_000, "mrt_distance_m": 100, "mrt_minutes_reported": 1, "mrt_operation_status": "under_construction"},
        ]
        by_id = {item["listing"]["listing_id"]: item for item in rank_listings(listings, preferences)}

        self.assertEqual(by_id["near"]["factors"]["mrt"], {"ratio": 0.5, "weight": 0.5})
        for listing_id in ("none", "uc"):
            self.assertEqual(by_id[listing_id]["factors"]["mrt"], {"ratio": 1.0, "no_data": True, "weight": 0.5})
        self.assertIsNone(mrt_minutes(listings[2]))

    def test_ties_go_to_mrt_before_rent(self):
        preferences = SearchPreferences(max_price_sgd=2_000)
        listings = [
            {"listing_id": "cheap", "rent_monthly_sgd": 400, "mrt_distance_m": 680, "mrt_operation_status": "operational"},
            {"listing_id": "near", "rent_monthly_sgd": 1_600, "mrt_distance_m": 170, "mrt_operation_status": "operational"},
        ]
        ranked = rank_listings(listings, preferences)

        self.assertEqual([item["rank_value"] for item in ranked], [0.5, 0.5])
        self.assertEqual([item["listing"]["listing_id"] for item in ranked], ["near", "cheap"])

    def test_new_conditions_filter_in_sql(self):
        with closing(create_database()) as connection:
            def values(column, **preferences):
                return {listing[column] for listing in search_listings(connection, SearchPreferences(**preferences))}

            self.assertEqual(values("gender_restriction", tenant_gender="female"), {"female_only", "no_restriction"})
            self.assertEqual(values("gender_restriction", tenant_gender="male"), {"male_only", "no_restriction"})
            self.assertEqual(values("gender_restriction", tenant_gender="mixed"), {"no_restriction"})
            self.assertEqual(values("landlord_lives_in", landlord_not_living_in=True), {"no"})
            self.assertNotIn("unfurnished", values("furnishing", furnished_required=True))
            self.assertEqual(values("air_conditioning", air_conditioning_required=True), {"yes"})

    def test_faculty_commutes_load_from_an_optional_file(self):
        with closing(create_database()) as connection:
            first, second = [listing["listing_id"] for listing in load_listings(connection)[:2]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "commute_faculty.csv"
            path.write_text(
                "listing_id,faculty,minutes,mode,departure\n"
                f"{first},School of Computing,8,walk,2026-10-12 08:30\n"
                f"{first},Faculty of Law,51,transit,2026-10-12 08:30\n"
                f"{second},School of Computing,,,2026-10-12 08:30\n",
                encoding="utf-8",
            )
            # A file from before walking checks has no mode column: its times are by public transport.
            old = Path(folder) / "old.csv"
            old.write_text(f"listing_id,faculty,minutes,departure\n{first},Faculty of Law,51,2026-10-12 08:30\n", encoding="utf-8")
            with closing(create_database(commute_path=path)) as connection:
                loaded = {listing["listing_id"]: listing["commutes"] for listing in load_listings(connection)}
            with closing(create_database(commute_path=old)) as connection:
                before_walking = {listing["listing_id"]: listing["commutes"] for listing in load_listings(connection)}
            with closing(create_database(commute_path=Path(folder) / "missing.csv")) as connection:
                missing = [listing["commutes"] for listing in load_listings(connection)]

        self.assertEqual(loaded[first], {
            "School of Computing": {"minutes": 8, "mode": "walk"},
            "Faculty of Law": {"minutes": 51, "mode": "transit"},
        })
        self.assertEqual(before_walking[first], {"Faculty of Law": {"minutes": 51, "mode": "transit"}})
        # An empty cell is a route OneMap could not find: no data, not zero minutes.
        self.assertEqual(loaded[second], {})
        self.assertTrue(all(commutes == {} for commutes in missing))
        listing = {"commutes": loaded[first]}
        self.assertEqual(commute_minutes(listing, SearchPreferences(faculty="Faculty of Law")), 51)
        self.assertIsNone(commute_minutes(listing, SearchPreferences()))

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
            connection.run(
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
            connection.run(
                "DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')"
            )

            # The top-ranked S010 has an unverified link and must keep first place.
            def checker(listing_id, url):
                return {
                    "status": "unknown" if listing_id == "S010" else "active",
                    "final_url": None if listing_id == "S010" else url,
                    "http_status": None if listing_id == "S010" else 200,
                    "error_reason": "network_error" if listing_id == "S010" else None,
                }

            validation = validate_ranked_listings(connection, ranked, checker)
            validated = validation["ranked_listings"]
            response = render_response(validated, check_summary=validation["summary"])

        self.assertEqual(
            [item["listing"]["listing_id"] for item in validated],
            ["S010", "S001"],
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
            connection.run("DELETE FROM listing_health")
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
            connection.run("DELETE FROM listing_health")
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

    def test_whole_dollar_rents_show_without_decimals(self):
        # Rents read from the delivery files and the database are decimals such as 2999.0.
        with closing(create_mock_database()) as connection:
            listing = {**load_listings(connection)[0], "rent_monthly_sgd": 2999.0}

        self.assertIn("Monthly rent: S$2,999\n", render_response([{"listing": listing}], language="en"))
        self.assertIn("月租：S$2,999\n", render_response([{"listing": listing}]))

    def test_live_validation_reports_unchecked_candidates_at_the_cap(self):
        with closing(create_mock_database()) as connection:
            ranked = [{"listing": listing} for listing in load_listings(connection)]
            connection.run("DELETE FROM listing_health")
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
            connection.run("DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')")

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
            connection.run("DELETE FROM listing_health WHERE listing_id = 'S001'")
            suggestions = analyze_relaxations(
                connection, preferences, checker=lambda *_: {"status": "inactive"}
            )

        self.assertEqual(suggestions, [])

    def test_only_keeps_small_area_review_warnings(self):
        with closing(create_mock_database()) as connection:
            connection.run(
                "UPDATE listings SET area_sqm = %s WHERE listing_id = %s",
                (930.42, "S010"),
            )
            connection.run(
                "UPDATE listing_metadata SET review_flags = %s WHERE listing_id = %s",
                (["area_outside_review_range", "tenant_count_scope_unconfirmed"], "S010"),
            )
            connection.run(
                "UPDATE listings SET area_sqm = %s WHERE listing_id = %s",
                (4.09, "S009"),
            )
            connection.run(
                "UPDATE listing_metadata SET review_flags = %s WHERE listing_id = %s",
                (["area_outside_review_range"], "S009"),
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

    def test_uses_850_metres_for_a_soft_mrt_preference(self):
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
        # S010 walks 310 m: 310 / 850 = 0.365.
        self.assertEqual([item["rank_value"] for item in ranking], [0.511, 0.701])
        self.assertEqual(ranking[0]["factors"]["mrt"]["ratio"], 0.365)
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
            # A 10-minute limit is an 850 m reference: S010 (310 m) and S001 (560 m).
            self.assertEqual([item["rank_value"] for item in ranking], [0.675, 0.791])
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

            # A OneMap walking route replaces the card distance.
            matches[0]["mrt_walk_distance_m"] = 85
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
                    "furnishing": "unknown",
                    "air_conditioning": "unknown",
                "private_bathroom": "unknown",
                "pets": "unknown",
                    "visitors": "unknown",
                    "smoking": "unknown",
                },
            )
            self.assertEqual(extract_restrictions(by_id["S009"])["cooking"], "unknown")

        with self.assertRaises(ValueError):
            SearchPreferences(max_price_sgd=0)

    def test_mrt_walk_refresh_is_persisted_and_reused(self):
        with closing(create_mock_database()) as connection:
            pending = connection.query(
                """
                SELECT count(*) AS n FROM agent_listings
                WHERE live_status <> 'inactive'
                  AND address IS NOT NULL AND trim(address) <> ''
                  AND mrt_station <> 'unknown' AND trim(mrt_station) <> ''
                """
            )[0]["n"]
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
