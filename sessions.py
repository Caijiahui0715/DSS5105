"""Where conversations, accounts and kept profiles live: the agent schema of the project's PostgreSQL.

They share the backend's connection pool (group_db.Database); LangGraph's checkpoint tables are made
in the same schema.
"""

from datetime import datetime
from uuid import uuid4

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from group_db import Database

# The state holds these Pydantic models; loading refuses any other class.
STATE_MODULES = [("models", "SearchPreferences"), ("models", "NearbyLocation")]
_TABLES = (
    "CREATE TABLE IF NOT EXISTS threads ("
    "thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
)


def serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_MODULES)


class Storage:
    """The agent's own tables, for request threads; accounts.py and profiles.py add theirs."""

    def __init__(self, database: Database):
        self.database = database
        for statement in _TABLES:
            self.run(statement)

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        return [tuple(row.values()) for row in self.database.query(sql, params)]

    def run(self, sql: str, params: tuple = ()) -> int:
        """Execute a write and return how many rows it changed."""
        return self.database.run(sql, params)

    # Conversations: each belongs to one user, listed by latest activity.

    def new_thread(self, user_id: str) -> str:
        # No "/" so the id can sit in a URL path.
        thread_id = f"{user_id}.{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
        now = _now()
        self.run("INSERT INTO threads VALUES (%s, %s, '', %s, %s)", (thread_id, user_id, now, now))
        return thread_id

    def threads(self, user_id: str) -> list[dict]:
        rows = self.rows(
            "SELECT thread_id, title, created_at, updated_at FROM threads WHERE user_id = %s "
            "ORDER BY updated_at DESC, created_at DESC",
            (user_id,),
        )
        return [dict(zip(("id", "title", "created_at", "updated_at"), row)) for row in rows]

    def owns(self, user_id: str, thread_id: str) -> bool:
        return bool(self.rows("SELECT 1 FROM threads WHERE thread_id = %s AND user_id = %s", (thread_id, user_id)))

    def touch(self, thread_id: str, message: str) -> None:
        """Record activity; the first message becomes the title."""
        self.run(
            "UPDATE threads SET updated_at = %s, title = CASE WHEN title = '' THEN %s ELSE title END WHERE thread_id = %s",
            (_now(), " ".join(message.split())[:20], thread_id),
        )

    def forget_thread(self, thread_id: str) -> None:
        self.run("DELETE FROM threads WHERE thread_id = %s", (thread_id,))

    def latest_thread(self, user_id: str) -> str | None:
        threads = self.threads(user_id)
        return threads[0]["id"] if threads else None


def open_storage(database: Database) -> tuple[Storage, PostgresSaver]:
    """The Storage for the agent's tables and a checkpointer for conversation states."""
    saver = PostgresSaver(database.pool, serde=serializer())
    saver.setup()
    return Storage(database), saver


def _now() -> str:
    # Milliseconds so conversations used within the same second still sort by activity.
    return datetime.now().isoformat(timespec="milliseconds")
