import unittest
from datetime import date

from mock_db import empty_storage
from profiles import EXCLUDED, SHORTLIST, UserProfiles, merged


class UserProfilesTest(unittest.TestCase):
    def test_saving_switches_memory_on_and_off_only_pauses_it(self):
        profiles = UserProfiles(empty_storage())
        kept = {"preferences": {"max_price_sgd": 1300}, "saved_on": "2026-10-05"}

        # Undecided: saving is itself agreement.
        self.assertIsNone(profiles.consent("alice"))
        self.assertIsNone(profiles.profile("alice"))
        self.assertTrue(profiles.save("alice", kept))
        self.assertTrue(profiles.consent("alice"))
        self.assertEqual(profiles.active_profile("alice"), kept)
        self.assertIsNone(profiles.profile("bob"))

        # Off keeps what is there, unused and unchanged; on uses it again.
        profiles.set_consent("alice", False)
        self.assertEqual(profiles.profile("alice"), kept)
        self.assertIsNone(profiles.active_profile("alice"))
        self.assertFalse(profiles.save("alice", {"preferences": {"max_price_sgd": 2000}}))
        self.assertEqual(profiles.profile("alice"), kept)
        profiles.set_consent("alice", True)
        self.assertEqual(profiles.active_profile("alice"), kept)
        self.assertEqual(profiles.all_profiles(), [("alice", kept)])

        # Deleting leaves the switch; forgetting also switches it off.
        profiles.delete_profile("alice")
        self.assertIsNone(profiles.profile("alice"))
        self.assertTrue(profiles.consent("alice"))
        profiles.save("alice", kept)
        profiles.forget("alice")
        self.assertIsNone(profiles.profile("alice"))
        self.assertFalse(profiles.consent("alice"))

    def test_the_faculty_is_an_account_setting_cleared_only_with_all_data(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_faculty("alice", "Faculty of Law")
        profiles.set_faculty("alice", "School of Computing")
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        self.assertIsNone(profiles.faculty("bob"))
        # 忘掉我的信息 deletes the kept criteria only; 删除我的全部数据 deletes the faculty too.
        profiles.forget("alice")
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        profiles.delete("alice")
        self.assertIsNone(profiles.faculty("alice"))
        profiles.set_faculty("bob", "Faculty of Law")
        profiles.set_faculty("bob", None)
        self.assertIsNone(profiles.faculty("bob"))

    def test_a_listing_is_either_shortlisted_or_excluded_in_the_order_added(self):
        profiles = UserProfiles(empty_storage())
        profiles.mark("alice", ["S001", "S002", "S003"], SHORTLIST)
        profiles.mark("alice", ["S002"], EXCLUDED)
        # Shortlisting again keeps the place; one moved back goes to the end.
        profiles.mark("alice", ["S001"], SHORTLIST)
        self.assertEqual(profiles.listings("alice"), (["S001", "S003"], ["S002"]))
        profiles.mark("alice", ["S002"], SHORTLIST)
        self.assertEqual(profiles.listings("alice"), (["S001", "S003", "S002"], []))
        # Removing from one list leaves the other alone; other users have their own.
        profiles.mark("alice", ["S004"], EXCLUDED)
        profiles.unmark("alice", ["S004"], SHORTLIST)
        profiles.unmark("alice", ["S001"], SHORTLIST)
        self.assertEqual(profiles.listings("alice"), (["S003", "S002"], ["S004"]))
        self.assertEqual(profiles.listings("bob"), ([], []))
        profiles.forget("alice")
        self.assertEqual(profiles.listings("alice"), (["S003", "S002"], ["S004"]))
        profiles.delete("alice")
        self.assertEqual(profiles.listings("alice"), ([], []))

    def test_merging_changes_keeps_the_other_criteria_and_their_sources(self):
        kept = {
            "preferences": {"max_price_sgd": 4773, "district_code": "D05"},
            "sources": {"max_price_sgd": {"quote": "一年30万人民币", "date": "2026-10-05"}, "district_code": {"quote": "D05", "date": "2026-10-05"}},
            "budget": {"amount": 300000, "currency": "CNY", "months": 12},
            "saved_on": "2026-10-05",
        }
        page = {"via": "profile", "date": "2026-10-19"}
        district = merged(kept, {"district_code": "D03", "rental_scope": "room"}, {"district_code": page}, None)
        self.assertEqual(district["preferences"], {"max_price_sgd": 4773, "district_code": "D03", "rental_scope": "room"})
        self.assertEqual(district["sources"]["district_code"], page)
        self.assertEqual(district["sources"]["rental_scope"], {"date": date.today().isoformat()})
        # The budget as stated stays while the budget does not change.
        self.assertEqual(district["budget"], kept["budget"])
        budget = merged(kept, {"max_price_sgd": 3000, "district_code": None}, {"max_price_sgd": page}, None)
        self.assertEqual(budget["preferences"], {"max_price_sgd": 3000})
        self.assertEqual(budget["sources"], {"max_price_sgd": page})
        self.assertIsNone(budget["budget"])
        self.assertEqual(merged(None, {}, {}, None)["preferences"], {})


if __name__ == "__main__":
    unittest.main()
