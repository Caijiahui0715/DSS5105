import unittest
from contextlib import closing
from itertools import product
from pathlib import Path

from decision import (
    budget_ladder,
    condition_status,
    default_budget_levels,
    diagnose_conditions,
    explain_listing,
    load_source_evidence,
    rental_scope_mix,
    search_with_unknowns,
)
from mock_db import create_database, create_mock_database
from models import SearchPreferences
from response import render_listing_details, render_listing_explanation
from tools import get_listings_by_ids, rank_listings, search_listings


class DecisionTest(unittest.TestCase):
    def test_strict_matches_are_exactly_the_sql_search(self):
        grid = product(
            (None, 1000, 2500),
            (None, "common_room", "Master Room", "studio"),
            (None, "entire_unit", "room"),
            (None, "D05"),
            (None, 8),
            (None, 2),
            (None, 2),
            (False, True),
        )
        with closing(create_database()) as connection:
            for price, room, scope, district, mrt, bedrooms, occupants, cooking in grid:
                preferences = SearchPreferences(
                    max_price_sgd=price,
                    room_type=room,
                    rental_scope=scope,
                    district_code=district,
                    max_mrt_minutes=mrt,
                    min_bedrooms=bedrooms,
                    occupant_count=occupants,
                    cooking_required=cooking,
                )
                with self.subTest(preferences=preferences):
                    strict, _ = search_with_unknowns(connection, preferences)
                    self.assertEqual(
                        [listing["listing_id"] for listing in strict],
                        [listing["listing_id"] for listing in search_listings(connection, preferences)],
                    )

    def test_property_types_match_the_sql_search(self):
        grid = product(
            (None, ("condominium", "apartment"), ("hdb_flat",)),
            (None, 1500),
            (None, "room"),
            (False, True),
        )
        with closing(create_database()) as connection:
            for property_types, price, scope, cooking in grid:
                preferences = SearchPreferences(
                    property_types=property_types,
                    max_price_sgd=price,
                    rental_scope=scope,
                    cooking_required=cooking,
                )
                with self.subTest(preferences=preferences):
                    strict, pending = search_with_unknowns(connection, preferences)
                    self.assertEqual(
                        [listing["listing_id"] for listing in strict],
                        [listing["listing_id"] for listing in search_listings(connection, preferences)],
                    )
                    if property_types:
                        self.assertTrue({listing["property_type"] for listing in strict + pending} <= set(property_types))

    def test_budget_ladder_counts_each_budget_with_other_conditions_kept(self):
        preferences = SearchPreferences(max_price_sgd=1300, cooking_required=True)
        levels = [1300, *default_budget_levels(1300), None]
        with closing(create_database()) as connection:
            rows = budget_ladder(connection, preferences, levels)
            expected = [
                search_with_unknowns(connection, preferences.model_copy(update={"max_price_sgd": level}))
                for level in levels
            ]

        self.assertEqual(default_budget_levels(1300), [1500, 2000, 3000])
        self.assertEqual([row["max_price_sgd"] for row in rows], levels)
        for row, (strict, pending) in zip(rows, expected):
            self.assertEqual(row["strict_matches"]["count"], len(strict))
            self.assertEqual(row["needs_confirmation"]["count"], len(pending))
            self.assertLessEqual(row["needs_confirmation"]["mrt_within_10_min"], len(pending))
        # V2 states cooking for rooms at many prices, so a higher budget adds strict matches.
        self.assertLess(rows[0]["strict_matches"]["count"], rows[-1]["strict_matches"]["count"])

    def test_unstated_conditions_need_confirmation_instead_of_failing(self):
        preferences = SearchPreferences(
            max_price_sgd=1000,
            room_type="common_room",
            cooking_required=True,
        )
        with closing(create_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)

        self.assertTrue(strict)
        self.assertTrue(all(listing["cooking_policy"] in {"allowed", "light_only"} for listing in strict))
        self.assertTrue(pending)
        for listing in pending:
            self.assertIn("cooking_required", listing["unknown_conditions"])
            self.assertLessEqual(listing["rent_monthly_sgd"], 1000)
            self.assertNotEqual(listing["cooking_policy"], "not_allowed")

    def test_room_types_must_fit_the_rental_scope(self):
        with closing(create_database()) as connection:
            _, rooms = search_with_unknowns(connection, SearchPreferences(room_type="common_room"))
            _, studios = search_with_unknowns(connection, SearchPreferences(room_type="studio"))

        self.assertTrue(rooms and studios)
        self.assertNotIn("entire_unit", {listing["rental_scope"] for listing in rooms})
        self.assertNotIn("room", {listing["rental_scope"] for listing in studios})

    def test_whole_unit_requests_keep_unstated_scope_for_confirmation(self):
        with closing(create_database()) as connection:
            strict, pending = search_with_unknowns(
                connection, SearchPreferences(rental_scope="entire_unit")
            )

        self.assertTrue(strict)
        self.assertEqual({listing["rental_scope"] for listing in strict}, {"entire_unit"})
        self.assertEqual({listing["rental_scope"] for listing in pending}, {"unknown"})
        self.assertTrue(all(listing["unknown_conditions"] == ["rental_scope"] for listing in pending))

    def test_diagnosis_reports_what_dropping_each_condition_yields(self):
        preferences = SearchPreferences(
            max_price_sgd=1000,
            room_type="common_room",
            cooking_required=True,
        )
        with closing(create_database()) as connection:
            rows = {
                row["condition"]: row
                for row in diagnose_conditions(connection, preferences)
            }
            without_cooking = search_listings(
                connection, preferences.model_copy(update={"cooking_required": False})
            )
            without_budget = search_listings(
                connection, preferences.model_copy(update={"max_price_sgd": None})
            )
            strict = search_listings(connection, preferences)

        cooking = rows["cooking_required"]
        self.assertEqual(set(rows), {"max_price_sgd", "room_type", "cooking_required"})
        self.assertEqual(cooking["database_matches_without_it"], len(without_cooking))
        self.assertGreater(cooking["unknown"], 0)
        self.assertEqual(cooking["unknown"] + cooking["known_fail"] + len(strict), len(without_cooking))
        self.assertEqual(
            rows["max_price_sgd"]["smallest_limit_with_a_match"],
            min(listing["rent_monthly_sgd"] for listing in without_budget),
        )

    def test_explanation_links_the_ranking_to_source_evidence(self):
        preferences = SearchPreferences(max_price_sgd=2000)
        with closing(create_database()) as connection:
            listing = search_listings(connection, preferences)[0]
        explanation = explain_listing(
            listing,
            preferences,
            load_source_evidence().get(listing["listing_id"]),
        )

        self.assertEqual(
            explanation["factors"]["price"]["ratio"],
            round(listing["rent_monthly_sgd"] / 2000, 3),
        )
        self.assertEqual(explanation["conditions"], {"max_price_sgd": "pass"})
        self.assertEqual(explanation["sources"]["rent_monthly_sgd"], "listing_card")
        self.assertIn("S$", explanation["evidence"]["card_text"])

    def test_explanation_names_the_rent_source(self):
        preferences = SearchPreferences(max_price_sgd=6000)
        with closing(create_database()) as connection:
            rechecked, card_only = get_listings_by_ids(connection, ["24842419", "500253628"])
        explanation = explain_listing(rechecked, preferences)
        text = render_listing_explanation(explanation)

        self.assertEqual(explanation["sources"]["rent_monthly_sgd"], "rechecked_listing")
        self.assertEqual(explain_listing(card_only, preferences)["sources"]["rent_monthly_sgd"], "listing_card")
        self.assertIn("月租来自重新采集的现价", text)
        self.assertIn("采集时房源卡片为 S$5,900，现价 S$5,800", text)

    def test_a_stated_priority_without_data_needs_confirmation(self):
        preferences = SearchPreferences(max_price_sgd=1500, ranking_priority="amenities")
        with closing(create_mock_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)

        # The legacy fixture has no nearby counts, so nothing can be ranked on food.
        self.assertEqual(strict, [])
        self.assertTrue(pending)
        self.assertTrue(all(listing["unknown_conditions"] == ["nearby_food"] for listing in pending))

    def test_new_conditions_match_the_sql_search(self):
        grid = product(
            (None, "female", "male", "mixed"),
            (False, True),
            (False, True),
            (False, True),
            (None, 1500),
            (None, "room", "entire_unit"),
            ("balanced", "mrt", "commute"),
        )
        with closing(create_database()) as connection:
            for gender, no_landlord, furnished, aircon, price, scope, priority in grid:
                preferences = SearchPreferences(
                    tenant_gender=gender,
                    landlord_not_living_in=no_landlord,
                    furnished_required=furnished,
                    air_conditioning_required=aircon,
                    max_price_sgd=price,
                    rental_scope=scope,
                    ranking_priority=priority,
                )
                with self.subTest(preferences=preferences):
                    strict, _ = search_with_unknowns(connection, preferences)
                    self.assertEqual(
                        [listing["listing_id"] for listing in strict],
                        [listing["listing_id"] for listing in search_listings(connection, preferences)],
                    )

    def test_tenant_gender_and_live_in_landlord_are_three_state(self):
        def status(field, wanted, **listing):
            return condition_status(field, listing, SearchPreferences(**{field: wanted}))

        self.assertEqual(status("tenant_gender", "female", gender_restriction="female_only"), "pass")
        self.assertEqual(status("tenant_gender", "female", gender_restriction="no_restriction"), "pass")
        self.assertEqual(status("tenant_gender", "female", gender_restriction="male_only"), "fail")
        self.assertEqual(status("tenant_gender", "male", gender_restriction="female_only"), "fail")
        self.assertEqual(status("tenant_gender", "mixed", gender_restriction="female_only"), "fail")
        self.assertEqual(status("tenant_gender", "mixed", gender_restriction="no_restriction"), "pass")
        # Unstated stays unknown, whole units included: the data does not say.
        self.assertEqual(status("tenant_gender", "female", gender_restriction="unknown", rental_scope="entire_unit"), "unknown")
        self.assertEqual(status("landlord_not_living_in", True, landlord_lives_in="no"), "pass")
        self.assertEqual(status("landlord_not_living_in", True, landlord_lives_in="yes"), "fail")
        self.assertEqual(status("landlord_not_living_in", True, landlord_lives_in="unknown", rental_scope="entire_unit"), "unknown")
        self.assertEqual(status("furnished_required", True, furnishing="partially_furnished"), "pass")
        self.assertEqual(status("furnished_required", True, furnishing="unfurnished"), "fail")
        self.assertEqual(status("air_conditioning_required", True, air_conditioning="unknown"), "unknown")
        self.assertEqual(status("max_commute_minutes", 40, commute_nus_minutes=35), "pass")
        self.assertEqual(status("max_commute_minutes", 40, commute_nus_minutes=None), "unknown")

    def test_unstated_conditions_are_named_for_confirmation(self):
        preferences = SearchPreferences(max_price_sgd=1200, tenant_gender="female", landlord_not_living_in=True)
        with closing(create_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)
            rows = {row["condition"]: row for row in diagnose_conditions(connection, preferences)}

        self.assertTrue(strict)
        self.assertTrue(all(listing["gender_restriction"] in {"female_only", "no_restriction"} for listing in strict))
        self.assertTrue(all(listing["landlord_lives_in"] == "no" for listing in strict))
        self.assertEqual(
            {condition for listing in pending for condition in listing["unknown_conditions"]},
            {"tenant_gender", "landlord_not_living_in"},
        )
        self.assertGreater(rows["landlord_not_living_in"]["unknown"], 0)

    def test_nus_commute_uses_the_loaded_minutes(self):
        preferences = SearchPreferences(max_price_sgd=1500, max_commute_minutes=30)
        with closing(create_mock_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)
            priority = SearchPreferences(max_price_sgd=1500, ranking_priority="commute")
            ranked = rank_listings(search_with_unknowns(connection, priority)[0], priority)

        # Mock minutes: S006 25, S010 28, S001 35; S009 has none.
        self.assertEqual({listing["listing_id"] for listing in strict}, {"S006", "S010"})
        self.assertIn("S009", {listing["listing_id"] for listing in pending})
        self.assertEqual(ranked[0]["listing"]["listing_id"], "S006")
        self.assertEqual(ranked[0]["factors"]["commute"]["weight"], 0.7)

    def test_mrt_priority_sends_listings_without_mrt_data_to_confirmation(self):
        preferences = SearchPreferences(max_price_sgd=8000, ranking_priority="mrt")
        with closing(create_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)

        self.assertTrue(pending)
        self.assertTrue(all(listing["unknown_conditions"] == ["max_mrt_minutes"] for listing in pending))
        # A station still under construction does not count as MRT access.
        self.assertIn("under_construction", {listing["mrt_operation_status"] for listing in pending})
        self.assertNotIn("under_construction", {listing["mrt_operation_status"] for listing in strict})

    def test_area_filters_and_space_ranking_respect_rental_scope(self):
        with closing(create_mock_database()) as connection:
            connection.execute("UPDATE listings SET area_sqm = NULL, area_scope = 'unknown', mrt_distance_m = 425")
            connection.executemany(
                "UPDATE listings SET area_sqm = ?, rental_scope = ?, area_scope = ? WHERE listing_id = ?",
                [
                    (200, "room", "floor_reported", "S001"),  # The room's own size is unknown.
                    (20, "room", "room_reported", "S002"),
                    (10, "room", "room_reported", "S004"),
                    (200, "entire_unit", "floor_reported", "S009"),
                    (100, "entire_unit", "floor_reported", "S010"),
                ],
            )
            for scope, minimum, priority in product((None, "room", "entire_unit"), (None, 15, 150), ("balanced", "space")):
                preferences = SearchPreferences(rental_scope=scope, min_area_sqm=minimum, ranking_priority=priority)
                with self.subTest(preferences=preferences):
                    strict, pending = search_with_unknowns(connection, preferences)
                    self.assertEqual(
                        [row["listing_id"] for row in strict],
                        [row["listing_id"] for row in search_listings(connection, preferences)],
                    )
                    if minimum or priority == "space":
                        self.assertNotIn("S001", {row["listing_id"] for row in strict})
                        if scope != "entire_unit":
                            self.assertIn("S001", {row["listing_id"] for row in pending})
                            self.assertTrue(all("min_area_sqm" in row["unknown_conditions"] for row in pending))
            preferences = SearchPreferences(ranking_priority="space")
            strict, _ = search_with_unknowns(connection, preferences)
            ranked = rank_listings(strict, preferences)
            by_id = {item["listing"]["listing_id"]: item for item in ranked}
            # Equally spacious within their own group; do not compare 20 sqm with 200 sqm.
            self.assertEqual(by_id["S002"]["factors"]["space"]["ratio"], by_id["S009"]["factors"]["space"]["ratio"])
            self.assertLess(by_id["S002"]["rank_value"], by_id["S004"]["rank_value"])
            self.assertLess(by_id["S009"]["rank_value"], by_id["S010"]["rank_value"])
            self.assertEqual(by_id["S002"]["rank_value"], explain_listing(by_id["S002"]["listing"], preferences)["rank_value"])
            wrong_scope = get_listings_by_ids(connection, ["S001"])[0]
            self.assertIn("房间面积未注明", render_listing_details(wrong_scope, {}, "zh"))
            self.assertIn("room area not stated", render_listing_details(wrong_scope, {}, "en"))
            self.assertTrue(explain_listing(wrong_scope, preferences)["factors"]["space"]["no_data"])

    def test_rental_scope_mix_names_the_other_kind(self):
        preferences = SearchPreferences(max_price_sgd=5000)
        with closing(create_database()) as connection:
            strict, _ = search_with_unknowns(connection, preferences)
            shown = [item["listing"] for item in rank_listings(strict, preferences)[:3]]
            room_only, _ = search_with_unknowns(connection, preferences.model_copy(update={"max_price_sgd": 1500}))

        mix = rental_scope_mix(preferences, strict, shown)
        self.assertEqual(mix["shown_scopes"], ["room"])
        self.assertEqual(mix["entire_unit"], {"database_count": 128, "cheapest_sgd": 2000})
        self.assertIsNone(rental_scope_mix(preferences.model_copy(update={"rental_scope": "room"}), strict, shown))
        # Under S$1,500 every match is a room, so there is no mix to mention.
        self.assertIsNone(rental_scope_mix(preferences, room_only, room_only[:3]))

    def test_a_missing_evidence_file_means_no_quotes(self):
        self.assertEqual(load_source_evidence(Path("missing-evidence.json")), {})


if __name__ == "__main__":
    unittest.main()
