import json
import unittest
from contextlib import closing
from datetime import date
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from decision import condition_status, diagnose_conditions, explain_listing, search_with_unknowns
from models import AMENITY_FIELDS, ParsedTurn, SearchPreferences
from mock_db import create_database, create_mock_database
from onemap import OneMapError, OneMapNotFound, geocode_location
from parser import parse_turn
from response import render_listing_explanation
from tests.test_agent import ScriptedModel, run_agent, tool_calls
from tools import _location_coordinates, location_distance_m, rank_listings, search_listings


class PreferenceIntegrationTest(unittest.TestCase):
    def test_new_constraints_are_pass_fail_unknown_and_match_strict_search(self):
        # Independent examples of supported user requirements, with a known match, failure and gap.
        cases = [
            ("min_bathrooms", 2, "bathrooms", 2, 1, None),
            ("private_bathroom_required", True, "private_bathroom", "yes", "no", "unknown"),
            ("pets_allowed_required", True, "pets_policy", "allowed", "not_allowed", "unknown"),
            ("rent_price_types", ["negotiable"], "rent_price_type", "negotiable", "starting_from", "unknown"),
            ("title_keyword", "test condo", "title", "The TEST CONDO", "Another home", "unknown"),
            ("address_keyword", "Clementi", "address", "123 CLEMENTI Road", "Dover Road", "unknown"),
            ("street_name", "Clementi", "street_name", "Clementi Road", "Dover Road", None),
            ("postcode", "012345", "postcode", "012345", "112345", None),
            ("mrt_station", "Clementi", "mrt_station", "EW23 Clementi MRT", "EW22 Dover MRT", "unknown"),
            ("min_mrt_stations", 2, "pg_mrt_count", 2, 1, None),
            ("max_mrt_distance_m", 500, "mrt_distance_m", 400, 600, None),
            ("min_food_places", 20, "poi_fnb_1km", 30, 10, None),
            ("min_hawker_centres", 2, "poi_hawker_1km", 2, 0, None),
            ("min_libraries", 1, "poi_library_1km", 1, 0, None),
            ("min_sports_facilities", 1, "poi_sport_1km", 1, 0, None),
            ("min_healthcare_places", 1, "poi_healthcare_1km", 1, 0, None),
            ("min_community_centres", 1, "poi_community_1km", 1, 0, None),
            ("min_schools", 10, "pg_school_count", 20, 5, None),
            ("max_school_walk_m", 500, "pg_school_nearest_walk_m", 400, 600, None),
            ("max_school_walk_minutes", 10, "pg_school_nearest_walk_min", 5, 15, None),
            ("listed_after", date(2026, 9, 10), "listed_date", "2026-09-12", "2026-09-01", "unknown"),
            ("furnishing_types", ["fully_furnished"], "furnishing", "fully_furnished", "partially_furnished", "furnished_unspecified"),
            ("cooking_level", "full", "cooking_policy", "allowed", "light_only", "unknown"),
            ("gender_preference", "female", "gender_preference", "female", "male", "unknown"),
        ]
        for field, wanted, column, passing, failing, unstated in cases:
            with self.subTest(field=field), closing(create_mock_database()) as db:
                excluded = [row[0] for row in db.execute("SELECT listing_id FROM listings") if row[0] not in {"S001", "S002", "S004"}]
                db.executemany(f"UPDATE listings SET {column} = ? WHERE listing_id = ?", [(passing, "S001"), (failing, "S002"), (unstated, "S004")])
                preferences = SearchPreferences(**{field: wanted})
                strict, pending = search_with_unknowns(db, preferences, excluded)
                self.assertEqual([row["listing_id"] for row in strict], ["S001"])
                self.assertEqual([row["listing_id"] for row in pending], ["S004"])
                self.assertEqual(pending[0]["unknown_conditions"], [field])
                self.assertEqual([row["listing_id"] for row in search_listings(db, preferences, excluded)], ["S001"])
                context = diagnose_conditions(db, preferences, excluded)[0]
                self.assertEqual((context["known_fail"], context["unknown"]), (1, 1))

    def test_facility_priorities_rank_the_actual_counts_and_explain_consistently(self):
        with closing(create_database()) as db:
            for priority, column in {**AMENITY_FIELDS, "school_distance": "pg_school_nearest_walk_min"}.items():
                with self.subTest(priority=priority):
                    preferences = SearchPreferences(ranking_priority=priority)
                    strict, pending = search_with_unknowns(db, preferences)
                    self.assertEqual({row["listing_id"] for row in strict}, {row["listing_id"] for row in search_listings(db, preferences)})
                    self.assertEqual(bool(pending), priority != "food_places")
                    # Equal MRT distance isolates the requested preference from other trade-offs.
                    candidates = [{**row, "mrt_walk_distance_m": 425, "mrt_operation_status": "operational"} for row in strict]
                    ranked = rank_listings(candidates, preferences)
                    first, last = ranked[0]["listing"], ranked[-1]["listing"]
                    if priority == "school_distance":
                        self.assertLess(first[column], last[column])
                    else:
                        self.assertGreater(first[column], last[column])
                    self.assertEqual(ranked[0]["factors"][priority]["weight"], 0.7)
                    explanation = explain_listing(first, preferences)
                    self.assertEqual(ranked[0]["rank_value"], explanation["rank_value"])
                    for language in ("zh", "en"):
                        self.assertIn("70%", render_listing_explanation(explanation, language))

    def test_location_radius_accounts_for_coordinate_error_and_missing_coordinates(self):
        preferences = SearchPreferences(nearby_location={"latitude": 1.3, "longitude": 103.77, "radius_m": 1000})
        for latitude, error, status in ((1.3, None, "pass"), (1.31, 0, "fail"), (1.309, "~500", "unknown"), (None, None, "unknown")):
            listing = {"latitude": latitude, "longitude": 103.77, "coord_error_m": error, "coord_source": "onemap_postcode"}
            self.assertEqual(condition_status("nearby_location", listing, preferences), status)
        with closing(create_database()) as db:
            strict, pending = search_with_unknowns(db, preferences)
            self.assertTrue(strict)
            self.assertEqual({row["listing_id"] for row in strict}, {row["listing_id"] for row in search_listings(db, preferences)})
            self.assertTrue(all(location_distance_m(row, preferences.nearby_location) <= 1000 for row in strict))
            self.assertTrue(all(row["unknown_conditions"] == ["nearby_location"] for row in pending))

    def test_new_requirements_are_saved_cleared_and_return_facts_in_the_agent(self):
        first_message = "必须全家具，至少两个卫生间，附近有图书馆"
        changes = {"furnishing_types": ["fully_furnished"], "min_bathrooms": 2, "min_libraries": 1}
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": changes, "user_quote": first_message})), AIMessage(content=""),
            tool_calls(("search_listings", {"clear": list(changes), "set": {"pets_allowed_required": True}, "user_quote": "改成只要求可以带宠物"})), AIMessage(content=""),
        )
        with closing(create_database()) as db:
            first, second = run_agent(db, model, first_message, "改成只要求可以带宠物")
        shown = json.loads(first["observations"][0])["strict_matches"]["listings"]
        self.assertEqual(len(shown), 3)
        self.assertTrue(all(row["bathrooms"] >= 2 and row["nearby_facility_counts"]["poi_library_1km"] >= 1 for row in shown))
        self.assertTrue(all(row["known_conditions"]["furnishing"] == "fully_furnished" for row in shown))
        self.assertIsNone(second["preferences"].furnishing_types)
        self.assertIsNone(second["preferences"].min_bathrooms)
        self.assertIsNone(second["preferences"].min_libraries)
        self.assertTrue(second["preferences"].pets_allowed_required)
        self.assertIn("允许宠物", second["response"])

    def test_location_is_resolved_once_and_survives_checkpoint_and_preview(self):
        _location_coordinates.cache_clear()
        message = "距离测试地点直线1500米以内"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"nearby_location": {"query": "test place", "radius_m": 1500}}, "user_quote": message})), AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"nearby_location": {"query": "test place", "radius_m": 2000}}, "preview": True})), AIMessage(content=""),
        )
        with closing(create_database()) as db, patch("tools.geocode_location", return_value=(1.3, 103.77)) as geocode:
            first, preview = run_agent(db, model, message, "如果扩大到2000米呢")
            geocode.assert_called_once_with("test place")
        self.assertEqual(preview["preferences"].nearby_location.radius_m, 1500)
        self.assertEqual(preview["preferences"].nearby_location.latitude, 1.3)
        shown = json.loads(first["observations"][0])["strict_matches"]["listings"]
        self.assertTrue(all(row["distance_to_reference_m"] <= 1500 for row in shown))
        _location_coordinates.cache_clear()

    def test_failed_geocoding_does_not_save_or_invent_a_location(self):
        _location_coordinates.cache_clear()
        message = "测试地点1500米以内"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"nearby_location": {"query": "missing place", "radius_m": 1500}}, "user_quote": message})),
            AIMessage(content="地点无法确认，请提供完整地址或坐标。"),
        )
        with closing(create_mock_database()) as db, patch("tools.geocode_location", side_effect=OneMapError("no match")):
            result, = run_agent(db, model, message)
        self.assertIsNone(result["preferences"].nearby_location)
        self.assertIn("Cannot resolve", result["observations"][0])

    def test_named_location_ambiguity_requires_a_more_precise_anchor(self):
        candidates = [{"LATITUDE": "1.3", "LONGITUDE": "103.77"}, {"LATITUDE": "1.4", "LONGITUDE": "103.78"}]
        with patch("onemap.load_token", return_value="test-token"), patch("onemap._get_json", return_value={"results": candidates}):
            with self.assertRaisesRegex(OneMapNotFound, "More than one place"):
                geocode_location("ambiguous place")
        # Multiple aliases at the same coordinates do establish one anchor.
        with patch("onemap.load_token", return_value="test-token"), patch("onemap._get_json", return_value={"results": [candidates[0], candidates[0]]}):
            self.assertEqual(geocode_location("exact place"), (1.3, 103.77))

    def test_workflow_parser_resolves_location_and_preserves_other_new_preferences(self):
        _location_coordinates.cache_clear()
        expected = ParsedTurn(intent="search", preferences=SearchPreferences(min_libraries=1, nearby_location={"query": "parser place", "radius_m": 500}))
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = expected
        with patch("tools.geocode_location", return_value=(1.3, 103.77)):
            turn = parse_turn("地点500米内，附近有图书馆", model)
        self.assertEqual(turn.preferences.min_libraries, 1)
        self.assertEqual(turn.preferences.nearby_location.latitude, 1.3)
        _location_coordinates.cache_clear()

    def test_precise_policies_and_location_inputs_are_validated(self):
        for changes in ({"cooking_required": True, "cooking_level": "none"}, {"furnished_required": True, "furnishing_types": ["unfurnished"]}, {"postcode": "12345"}, {"nearby_location": {"latitude": 1.3, "radius_m": 100}}, {"nearby_location": {"query": "x", "radius_m": -1}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SearchPreferences(**changes)
        # Unknown furnishing level is not a known failure for a fully furnished requirement.
        self.assertEqual(condition_status("furnishing_types", {"furnishing": "furnished_unspecified"}, SearchPreferences(furnishing_types=["fully_furnished"])), "unknown")
        self.assertEqual(condition_status("furnishing_types", {"furnishing": "furnished_unspecified"}, SearchPreferences(furnishing_types=["unfurnished"])), "fail")
        # A different MRT distance source is usable; a station under construction is not.
        prefs = SearchPreferences(max_mrt_distance_m=500)
        self.assertEqual(condition_status("max_mrt_distance_m", {"pg_mrt_nearest_walk_m": 400}, prefs), "pass")
        self.assertEqual(condition_status("max_mrt_distance_m", {"pg_mrt_nearest_walk_m": 400, "mrt_operation_status": "under_construction"}, prefs), "unknown")


if __name__ == "__main__":
    unittest.main()
