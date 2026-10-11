import unittest
from datetime import datetime, timedelta

from accounts import AccountError, Accounts
from mock_db import empty_storage


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 6, 12, 0)

    def __call__(self):
        return self.now


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.storage = empty_storage()
        self.accounts = Accounts(self.storage, clock=self.clock)

    def test_registration_rules(self):
        self.assertEqual(self.accounts.register("Alice_1", "correct horse"), "alice_1")
        for username, password in (("al", "long enough"), ("alice!", "long enough"), ("bob", "short")):
            with self.subTest(username=username), self.assertRaises(AccountError):
                self.accounts.register(username, password)
        with self.assertRaisesRegex(AccountError, "已被注册"):
            self.accounts.register("ALICE_1", "another password")
        # Only a salted hash is stored.
        stored = self.storage.rows("SELECT password_hash FROM users")[0][0]
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn("correct horse", stored)

    def test_login_tokens_expire_and_logout_ends_them(self):
        self.accounts.register("alice", "correct horse")
        user_id, token = self.accounts.login("Alice", "correct horse")
        self.assertEqual((user_id, self.accounts.user_for(token)), ("alice", "alice"))
        self.assertNotIn(token, str(self.storage.rows("SELECT * FROM auth_tokens")))
        self.assertIsNone(self.accounts.user_for("made-up"))

        _, other = self.accounts.login("alice", "correct horse")
        self.accounts.logout(token)
        self.assertIsNone(self.accounts.user_for(token))
        self.assertEqual(self.accounts.user_for(other), "alice")
        self.clock.now += timedelta(days=7, seconds=1)
        self.assertIsNone(self.accounts.user_for(other))

        _, again = self.accounts.login("alice", "correct horse")
        self.accounts.sign_out_everywhere("alice")
        self.assertIsNone(self.accounts.user_for(again))

    def test_five_wrong_passwords_lock_the_account_for_a_minute(self):
        self.accounts.register("alice", "correct horse")
        for _ in range(5):
            with self.assertRaisesRegex(AccountError, "用户名或密码不正确"):
                self.accounts.login("alice", "wrong password")
        # Locked even with the right password, then usable again after a minute.
        with self.assertRaisesRegex(AccountError, "1 分钟后再试"):
            self.accounts.login("alice", "correct horse")
        self.clock.now += timedelta(minutes=1, seconds=1)
        self.assertEqual(self.accounts.login("alice", "correct horse")[0], "alice")
        # An unknown user gets the same message as a wrong password.
        with self.assertRaisesRegex(AccountError, "用户名或密码不正确"):
            self.accounts.login("nobody", "whatever123")


if __name__ == "__main__":
    unittest.main()
