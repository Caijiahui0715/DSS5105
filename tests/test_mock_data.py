import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "mock_listings.json"

REMOVED_COLUMNS = {
    "postal_code",
    "latitude",
    "longitude",
    "private_bathroom",
    "furnishing",
    "air_conditioning",
    "cooking_policy",
    "wifi_included",
    "utilities_included",
    "utilities_monthly_sgd",
    "deposit_sgd",
    "agent_fee_sgd",
    "minimum_lease_months",
    "available_from",
    "maximum_occupants",
    "landlord_lives_in",
    "visitors_policy",
    "pets_policy",
    "smoking_policy",
    "student_eligibility",
    "washing_machine",
    "lift_access",
    "nus_destination",
    "nus_transit_minutes",
    "nus_transfers",
    "nus_walk_minutes",
    "route_departure_time",
    "route_checked_at",
    "monthly_total_sgd",
}

REQUIRED_FIELDS = {
    "listing_id",
    "title",
    "property_type",
    "listing_status_code",
    "availability_text",
    "price_sgd",
    "rental_scope",
    "room_type",
    "district_code",
    "address",
    "mrt_station",
    "mrt_distance_m",
    "mrt_minutes_reported",
    "url",
    "posted_at_text",
    "collected_at",
    "card_text",
    "field_evidence",
    "missing_fields",
    "review_flags",
}


class MockListingFixtureTest(unittest.TestCase):
    def test_fixture_contract_and_edge_cases(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        listings = payload["listings"]

        self.assertTrue(payload["metadata"]["synthetic"])
        self.assertEqual(payload["metadata"]["record_count"], len(listings))
        self.assertEqual(len({row["listing_id"] for row in listings}), len(listings))

        for row in listings:
            self.assertTrue(REQUIRED_FIELDS <= row.keys())
            self.assertFalse(REMOVED_COLUMNS & row.keys())
            self.assertFalse(REMOVED_COLUMNS & set(row["missing_fields"]))

        self.assertTrue(any(row["room_type"] == "Unknown" for row in listings))
        self.assertTrue(any(row["mrt_station"] is None for row in listings))
        self.assertTrue(any(row["review_flags"] for row in listings))
        self.assertTrue(any("No cooking" in row["card_text"] for row in listings))


if __name__ == "__main__":
    unittest.main()
