"""What is kept about each user across conversations.

The long-term profile: criteria the user chose to keep, which each new conversation starts from while
long-term memory is on. It changes only when the user saves: criteria changed in a conversation, or
edits on the Profile page. Each criterion keeps where it came from (the user's words and the date, or
the Profile page), and the budget as stated; never conversation text.

Long-term memory is a switch (consent): undecided until the user saves or answers, on, or off. Off
pauses it: what is kept stays and can be seen or deleted, but is neither used nor changed.

Shortlisted and excluded listings belong to the account and are shared by all its conversations,
whatever the switch. The NUS faculty is an account setting too, used for commute times everywhere.
"""

import json
from datetime import date, datetime

from sessions import Storage

SHORTLIST, EXCLUDED = "shortlist", "excluded"


class UserProfiles:
    def __init__(self, storage: Storage):
        self.storage = storage
        # consent: NULL until the user decides, 1 for on, 0 for off (what is kept stays).
        storage.run(
            "CREATE TABLE IF NOT EXISTS user_profiles ("
            "user_id TEXT PRIMARY KEY, consent INTEGER, profile TEXT, updated_at TEXT NOT NULL)"
        )
        storage.run(
            "CREATE TABLE IF NOT EXISTS user_faculties ("
            "user_id TEXT PRIMARY KEY, faculty TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        # A listing is either shortlisted or excluded; seq keeps the order they were added in.
        storage.run(
            "CREATE TABLE IF NOT EXISTS user_listings ("
            "user_id TEXT NOT NULL, listing_id TEXT NOT NULL, kind TEXT NOT NULL, seq BIGSERIAL, "
            "PRIMARY KEY (user_id, listing_id))"
        )
        # One-time data moves that already ran.
        storage.run("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, done_at TEXT NOT NULL)")

    # Long-term memory.

    def consent(self, user_id: str) -> bool | None:
        rows = self.storage.rows("SELECT consent FROM user_profiles WHERE user_id = %s", (user_id,))
        return None if not rows or rows[0][0] is None else bool(rows[0][0])

    def profile(self, user_id: str) -> dict | None:
        """What is kept, whether memory is on or off: for showing it."""
        rows = self.storage.rows("SELECT profile FROM user_profiles WHERE user_id = %s", (user_id,))
        return json.loads(rows[0][0]) if rows and rows[0][0] else None

    def all_profiles(self) -> list[tuple[str, dict]]:
        """(user_id, what is kept) of every user who has something kept."""
        return [(user_id, json.loads(profile)) for user_id, profile in self.storage.rows(
            "SELECT user_id, profile FROM user_profiles WHERE profile IS NOT NULL ORDER BY user_id"
        )]

    def active_profile(self, user_id: str) -> dict | None:
        """What is kept, only while memory is on: for using it in a conversation."""
        return self.profile(user_id) if self.consent(user_id) else None

    def set_consent(self, user_id: str, consent: bool) -> None:
        """Switch memory on or off; what is kept stays either way."""
        self.storage.run(
            "INSERT INTO user_profiles (user_id, consent, profile, updated_at) VALUES (%s, %s, NULL, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET consent = excluded.consent, updated_at = excluded.updated_at",
            (user_id, int(consent), _now()),
        )

    def save(self, user_id: str, profile: dict) -> bool:
        """Replace what is kept. Saving is itself agreement from a user who never decided, so it switches
        memory on; while memory is off nothing is written."""
        if self.consent(user_id) is None:
            self.set_consent(user_id, True)
        return bool(self.storage.run(
            "UPDATE user_profiles SET profile = %s, updated_at = %s WHERE user_id = %s AND consent = 1",
            (json.dumps(profile, ensure_ascii=False), _now(), user_id),
        ))

    def delete_profile(self, user_id: str) -> None:
        """Delete the kept criteria; the switch stays as it is."""
        self.storage.run("UPDATE user_profiles SET profile = NULL, updated_at = %s WHERE user_id = %s", (_now(), user_id))

    def forget(self, user_id: str) -> None:
        """Delete the kept criteria and switch memory off; listings and the faculty stay."""
        self.delete_profile(user_id)
        self.set_consent(user_id, False)

    def delete(self, user_id: str) -> None:
        """Remove every trace: the switch, the kept criteria, listings and the faculty."""
        for table in ("user_profiles", "user_faculties", "user_listings"):
            self.storage.run(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))

    # The account's shortlisted and excluded listings.

    def listings(self, user_id: str) -> tuple[list[str], list[str]]:
        """(shortlisted, excluded), each in the order added."""
        rows = self.storage.rows("SELECT listing_id, kind FROM user_listings WHERE user_id = %s ORDER BY seq", (user_id,))
        return [i for i, kind in rows if kind == SHORTLIST], [i for i, kind in rows if kind == EXCLUDED]

    def mark(self, user_id: str, listing_ids: list[str], kind: str) -> None:
        """Shortlist or exclude listings; a shortlisted listing that is excluded leaves the shortlist,
        and the other way round. One already marked this way keeps its place."""
        for listing_id in listing_ids:
            self.storage.run(
                "INSERT INTO user_listings (user_id, listing_id, kind) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, listing_id) DO UPDATE SET kind = excluded.kind, "
                "seq = CASE WHEN user_listings.kind = excluded.kind THEN user_listings.seq ELSE excluded.seq END",
                (user_id, listing_id, kind),
            )

    def unmark(self, user_id: str, listing_ids: list[str], kind: str) -> None:
        if listing_ids:
            self.storage.run(
                "DELETE FROM user_listings WHERE user_id = %s AND kind = %s AND listing_id = ANY(%s)",
                (user_id, kind, list(listing_ids)),
            )

    def migrated(self, name: str) -> bool:
        return bool(self.storage.rows("SELECT 1 FROM migrations WHERE name = %s", (name,)))

    def finish_migration(self, name: str) -> None:
        self.storage.run("INSERT INTO migrations VALUES (%s, %s) ON CONFLICT DO NOTHING", (name, _now()))

    # The NUS faculty.

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


def merged(kept: dict | None, changes: dict, sources: dict, budget: dict | None) -> dict:
    """kept with changes applied, as saved: changes maps a criterion to its new JSON value, or to None
    to drop it; sources gives each changed criterion's source. budget is the budget as stated when the
    budget changes (None for a plain monthly amount in SGD); otherwise the kept one stays."""
    kept = kept or {}
    preferences, kept_sources = dict(kept.get("preferences", {})), dict(kept.get("sources", {}))
    for field, value in changes.items():
        if value is None:
            preferences.pop(field, None)
            kept_sources.pop(field, None)
        else:
            preferences[field] = value
            kept_sources[field] = sources.get(field) or {"date": date.today().isoformat()}
    return {
        "preferences": preferences,
        "sources": kept_sources,
        "budget": budget if "max_price_sgd" in changes else kept.get("budget"),
        "saved_on": date.today().isoformat(),
    }


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
