"""What is kept about each user across conversations.

Long-term memory: the criteria a user agreed to keep, offered again in their later conversations.
Only what the agent already saved from the user's own words is kept (preferences with the quote
and date behind each field, the budget as stated, shortlist and exclusions), never free-form notes.

The user's NUS faculty is an account setting instead: chosen on the web page, or in a conversation
when the user confirms it, and used for commute times in every conversation.
"""

import json
from datetime import datetime

from sessions import Storage


class UserProfiles:
    def __init__(self, storage: Storage):
        self.storage = storage
        # consent: NULL until the user decides, 1 to keep the profile, 0 to keep nothing.
        storage.run(
            "CREATE TABLE IF NOT EXISTS user_profiles ("
            "user_id TEXT PRIMARY KEY, consent INTEGER, profile TEXT, updated_at TEXT NOT NULL)"
        )
        storage.run(
            "CREATE TABLE IF NOT EXISTS user_faculties ("
            "user_id TEXT PRIMARY KEY, faculty TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    def consent(self, user_id: str) -> bool | None:
        rows = self.storage.rows("SELECT consent FROM user_profiles WHERE user_id = %s", (user_id,))
        return None if not rows or rows[0][0] is None else bool(rows[0][0])

    def profile(self, user_id: str) -> dict | None:
        rows = self.storage.rows("SELECT profile FROM user_profiles WHERE user_id = %s AND consent = 1", (user_id,))
        return json.loads(rows[0][0]) if rows and rows[0][0] else None

    def set_consent(self, user_id: str, consent: bool) -> None:
        """Record the user's decision; declining also deletes anything kept."""
        self.storage.run(
            "INSERT INTO user_profiles (user_id, consent, profile, updated_at) VALUES (%s, %s, NULL, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET consent = excluded.consent, updated_at = excluded.updated_at, "
            "profile = CASE WHEN excluded.consent = 1 THEN user_profiles.profile END",
            (user_id, int(consent), _now()),
        )

    def save(self, user_id: str, profile: dict) -> bool:
        """Replace the kept profile; nothing is written without the user's consent."""
        return bool(self.storage.run(
            "UPDATE user_profiles SET profile = %s, updated_at = %s WHERE user_id = %s AND consent = 1",
            (json.dumps(profile, ensure_ascii=False), _now(), user_id),
        ))

    def forget(self, user_id: str) -> None:
        """Delete the kept criteria and keep nothing more; the faculty setting stays."""
        self.set_consent(user_id, False)

    def delete(self, user_id: str) -> None:
        """Remove every trace, the consent decision and the faculty included: the user is asked again later."""
        self.storage.run("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
        self.storage.run("DELETE FROM user_faculties WHERE user_id = %s", (user_id,))

    def faculty(self, user_id: str) -> str | None:
        rows = self.storage.rows("SELECT faculty FROM user_faculties WHERE user_id = %s", (user_id,))
        return rows[0][0] if rows else None

    def set_faculty(self, user_id: str, faculty: str | None) -> None:
        """Save a recorded faculty name, or clear the setting with None."""
        if faculty is None:
            self.storage.run("DELETE FROM user_faculties WHERE user_id = %s", (user_id,))
            return
        self.storage.run(
            "INSERT INTO user_faculties VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET faculty = excluded.faculty, updated_at = excluded.updated_at",
            (user_id, faculty, _now()),
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
