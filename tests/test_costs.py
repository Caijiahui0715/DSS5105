import unittest
from contextlib import closing

from costs import lease_costs
from decision import condition_status, search_with_unknowns
from mock_db import create_database
from models import SearchPreferences
from response import lease_text, render_costs, render_lease_minimum, render_response
from tools import analyze_relaxations, lease_term


def active(listing_id, url):
    return {"status": "active", "final_url": url, "http_status": 200}


class LeaseCostTest(unittest.TestCase):
    def test_a_two_year_lease(self):
        costs = lease_costs(3000, 24)

        self.assertEqual(costs["total_rent_sgd"], 72000)
        # 0.4% of the whole lease's rent.
        self.assertEqual(costs["stamp_duty_sgd"], 288)
        # One month of deposit per year of lease.
        self.assertEqual((costs["deposit_months"], costs["deposit_sgd"]), (2, 6000))
        self.assertIsNone(costs["agent_fee_sgd"])
        # Deposit, first month's rent and stamp duty; the deposit is not spent.
        self.assertEqual(costs["upfront_sgd"], 9288)
        self.assertEqual(costs["total_cost_sgd"], 72288)

    def test_stamp_duty_rounds_down_and_short_leases_still_pay_a_years_deposit(self):
        costs = lease_costs(1234.5, 6, agent=True)

        self.assertEqual(costs["total_rent_sgd"], 7407)
        self.assertEqual(costs["stamp_duty_sgd"], 29)
        self.assertEqual(costs["deposit_months"], 1)
        # Half a month's rent per year of lease, plus 9% GST.
        self.assertEqual((costs["agent_fee_sgd"], costs["agent_fee_gst_sgd"]), (617.25, 55.55))
        self.assertEqual(costs["upfront_sgd"], 1234.5 + 1234.5 + 29 + 617.25 + 55.55)

    def test_exemption_and_the_four_year_cap(self):
        self.assertEqual(lease_costs(80, 12)["stamp_duty_sgd"], 0)
        self.assertTrue(lease_costs(80, 12)["stamp_duty_exempt"])
        five_years = lease_costs(2000, 60)
        self.assertEqual(five_years["stamp_duty_base_sgd"], 96000)
        self.assertEqual(five_years["stamp_duty_sgd"], 384)

    def test_paid_at_signing_adds_up_the_rounded_parts(self):
        costs = lease_costs(83.33, 12, agent=True)
        parts = costs["deposit_sgd"] + costs["rent_monthly_sgd"] + costs["stamp_duty_sgd"] + costs["agent_fee_sgd"] + costs["agent_fee_gst_sgd"]
        self.assertEqual(costs["upfront_sgd"], round(parts, 2))

    def test_what_the_user_states_replaces_the_defaults(self):
        costs = lease_costs(2000, 12, deposit_months=2, agent=True, agent_fee=1000)

        self.assertEqual(costs["deposit_sgd"], 4000)
        # A stated fee is the whole amount: no GST is added.
        self.assertEqual((costs["agent_fee_sgd"], costs["agent_fee_gst_sgd"]), (1000, None))
        self.assertEqual(costs["upfront_sgd"], 4000 + 2000 + 96 + 1000)


class LeaseConditionTest(unittest.TestCase):
    def test_lease_terms_are_read_as_the_landlords_minimum(self):
        self.assertEqual(lease_term({"lease_term": "2 years"}), 24)
        self.assertEqual(lease_term({"lease_term": "1 year"}), 12)
        self.assertEqual(lease_term({"lease_term": "Flexible"}), "flexible")
        self.assertEqual(lease_term({"lease_term": "Short Term"}), "short_term")
        self.assertIsNone(lease_term({"lease_term": "Prefer not to say"}))
        self.assertIsNone(lease_term({"lease_term": None}))

    def test_whether_a_lease_fits(self):
        expected = {
            # advert: (6 months, 12 months, 24 months)
            "2 years": ("fail", "fail", "pass"),
            "1 year": ("fail", "pass", "pass"),
            "Flexible": ("pass", "pass", "pass"),
            "Short Term": ("pass", "unknown", "unknown"),
            "Prefer not to say": ("unknown", "unknown", "unknown"),
            None: ("unknown", "unknown", "unknown"),
        }
        for term, statuses in expected.items():
            for months, status in zip((6, 12, 24), statuses):
                with self.subTest(term=term, months=months):
                    self.assertEqual(
                        condition_status("lease_months", {"lease_term": term}, SearchPreferences(lease_months=months)),
                        status,
                    )

    def test_unstated_terms_need_confirmation_and_longer_leases_find_more(self):
        with closing(create_database()) as connection:
            counts = {}
            for months in (6, 12, 24):
                strict, pending = search_with_unknowns(connection, SearchPreferences(lease_months=months))
                counts[months] = len(strict)
                self.assertTrue(all("lease_months" in listing["unknown_conditions"] for listing in pending))
                self.assertTrue(all(lease_term(listing) != 24 or months >= 24 for listing in strict))

        self.assertLess(counts[6], counts[12])
        self.assertLess(counts[12], counts[24])

    def test_signing_for_longer_is_suggested_with_counts(self):
        preferences = SearchPreferences(lease_months=6, rental_scope="entire_unit", max_price_sgd=2500)
        with closing(create_database()) as connection:
            suggestions = analyze_relaxations(connection, preferences, checker=active)

        lease = [(item["suggested"], item["match_count"]) for item in suggestions if item["field"] == "lease_months"]
        self.assertEqual([months for months, _ in lease], [12, 24])
        self.assertTrue(all(count for _, count in lease))

    def test_the_lease_is_shown_with_each_listing(self):
        self.assertEqual(lease_text({"lease_term": "2 years"}, "zh"), "至少 2 年")
        self.assertEqual(lease_text({"lease_term": "1 year"}, "en"), "at least 1 year")
        self.assertEqual(lease_text({"lease_term": ""}, "zh"), "未注明")
        reply = render_response([{"listing": {"listing_id": "S001", "title": "Room", "rent_monthly_sgd": 1200, "lease_term": "Flexible"}}], language="en")
        self.assertIn("   Lease: flexible", reply)

    def test_short_leases_get_the_legal_minimums(self):
        self.assertIn("HDB", render_lease_minimum(2, "zh"))
        self.assertIn("3 months", render_lease_minimum(5, "en"))
        self.assertEqual(render_lease_minimum(6, "zh"), "")
        self.assertEqual(render_lease_minimum(None, "zh"), "")


class CostTextTest(unittest.TestCase):
    def row(self, rent, months, reason, **extra):
        return {
            "listing_id": extra.pop("listing_id", "S001"),
            "title": "Room",
            "rent_source": "listing",
            "lease_reason": reason,
            "listing_minimum_months": extra.pop("minimum", None),
            "your_lease_months": extra.pop("yours", None),
            "costs": lease_costs(rent, months, **extra),
        }

    def test_assumptions_come_first_and_the_offer_to_recalculate_last(self):
        text = render_costs([self.row(3000, 24, "listing", minimum=24)], "zh")
        lines = text.splitlines()

        self.assertEqual(lines[0], "费用估算：Room（S001）")
        self.assertEqual(lines[1], "假设：租期 24 个月（房源要求至少签 2 年）；押金 2 个月（每年租期 1 个月）；未包含中介费。")
        self.assertIn("- 印花税：S$72,000 × 0.4% = S$288（向下取整到元，最少 S$1）", lines)
        self.assertIn("- 签约时预付：押金 S$6,000 + 第一个月租金 S$3,000 + 印花税 S$288 = S$9,288", lines)
        self.assertIn("转为押金，不另外计入", text)
        self.assertEqual(lines[-1], "如果你打算签别的租期、押金月数不同或用了中介，告诉我，我重新算。")

    def test_a_listing_asking_for_longer_than_the_user_says(self):
        text = render_costs([self.row(1200, 24, "listing_over_yours", minimum=24, yours=6, agent=True)], "en")

        self.assertIn("a 24-month lease (this listing asks for at least 2 years, longer than the 6 months you gave)", text)
        self.assertIn("- Agent fee: S$1,200 × 0.5 × 2 = S$1,200, plus 9% GST S$108", text)
        self.assertIn("an agent fee estimated from common practice", text)

    def test_several_listings_are_compared(self):
        text = render_costs(
            [self.row(3000, 24, "listing", minimum=24), self.row(2500, 12, "default", listing_id="S002")],
            "zh",
        )

        self.assertIn("费用对比（2 套，各按自己的租期计算）：", text)
        # The leases differ, so the deposit is given as the rule rather than one count.
        self.assertIn("假设：押金每年租期 1 个月；未包含中介费。", text)
        self.assertIn("签约时预付最少：S002（S$5,120）", text)
        # A 24-month and a 12-month lease are compared by the average spent a month.
        self.assertIn("租期不同，按平均每月花费比较，最少的是 S002（每月 S$2,510）。", text)
        same = render_costs([self.row(3000, 12, "default"), self.row(2500, 12, "default", listing_id="S002")], "en")
        self.assertIn("least spent over the lease: S002 (S$30,120).", same)


if __name__ == "__main__":
    unittest.main()
