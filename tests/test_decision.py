import unittest
from contextlib import closing
from itertools import product
from pathlib import Path

from decision import (
    budget_ladder,
    default_budget_levels,
    diagnose_conditions,
    explain_listing,
    load_source_evidence,
    search_with_unknowns,
)
from mock_db import create_database
from models import SearchPreferences
from tools import search_listings


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
        self.assertEqual({row["strict_matches"]["count"] for row in rows}, {1})

    def test_unstated_conditions_need_confirmation_instead_of_failing(self):
        preferences = SearchPreferences(
            max_price_sgd=1000,
            room_type="common_room",
            cooking_required=True,
        )
        with closing(create_database()) as connection:
            strict, pending = search_with_unknowns(connection, preferences)

        self.assertEqual(strict, [])
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

        cooking = rows["cooking_required"]
        self.assertEqual(set(rows), {"max_price_sgd", "room_type", "cooking_required"})
        self.assertEqual(cooking["database_matches_without_it"], len(without_cooking))
        self.assertGreater(cooking["unknown"], 0)
        self.assertEqual(cooking["unknown"] + cooking["known_fail"], len(without_cooking))
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

    def test_a_missing_evidence_file_means_no_quotes(self):
        self.assertEqual(load_source_evidence(Path("missing-evidence.json")), {})


if __name__ == "__main__":
    unittest.main()
