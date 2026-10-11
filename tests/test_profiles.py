import unittest

from mock_db import empty_storage
from profiles import UserProfiles


class UserProfilesTest(unittest.TestCase):
    def test_nothing_is_kept_without_consent_and_forget_deletes_it(self):
        profiles = UserProfiles(empty_storage())
        kept = {"preferences": {"max_price_sgd": 1300}, "shortlisted_listing_ids": ["S001"]}

        # Undecided: nothing is written.
        self.assertIsNone(profiles.consent("alice"))
        self.assertFalse(profiles.save("alice", kept))
        self.assertIsNone(profiles.profile("alice"))

        profiles.set_consent("alice", True)
        self.assertTrue(profiles.save("alice", kept))
        self.assertEqual(profiles.profile("alice"), kept)
        # Agreeing again keeps what is there; other users are separate.
        profiles.set_consent("alice", True)
        self.assertEqual(profiles.profile("alice"), kept)
        self.assertIsNone(profiles.profile("bob"))

        profiles.forget("alice")
        self.assertFalse(profiles.consent("alice"))
        self.assertIsNone(profiles.profile("alice"))
        self.assertFalse(profiles.save("alice", kept))
        stored = profiles.storage.rows("SELECT profile FROM user_profiles WHERE user_id = 'alice'")
        self.assertEqual(stored, [(None,)])


    def test_the_faculty_is_an_account_setting_cleared_only_with_all_data(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_faculty("alice", "Faculty of Law")
        profiles.set_faculty("alice", "School of Computing")
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        self.assertIsNone(profiles.faculty("bob"))
        # 忘掉我的信息 deletes long-term memory only; 删除我的所有数据 deletes the faculty too.
        profiles.forget("alice")
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        profiles.delete("alice")
        self.assertIsNone(profiles.faculty("alice"))
        profiles.set_faculty("bob", "Faculty of Law")
        profiles.set_faculty("bob", None)
        self.assertIsNone(profiles.faculty("bob"))


if __name__ == "__main__":
    unittest.main()
