"""Where conversations, accounts and kept profiles live.

Local SQLite (sessions.sqlite) by default. With AGENT_DB=postgres in .env, everything goes to the
team's Postgres instead, in its own "agent" schema next to the listing tables, connecting with the
DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD variables the data pipeline already uses.
Tables and code paths are the same for both.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from config import postgres_settings, use_postgres

DEFAULT_PATH = Path(__file__).parent / "sessions.sqlite"
SCHEMA = "agent"
# The state holds these Pydantic models; loading refuses any other class.
STATE_MODULES = [("models", "SearchPreferences"), ("models", "NearbyLocation")]
_TABLES = (
    "CREATE TABLE IF NOT EXISTS threads ("
    "thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    # Replaced by threads: one row per conversation instead of each user's latest one.
    "DROP TABLE IF EXISTS user_sessions",
)


def serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_MODULES)


class Storage:
    """One database connection shared by request threads, for the agent's own tables."""

    def __init__(self, connection, postgres: bool = False):
        self.connection, self.postgres = connection, postgres
        self.lock = threading.Lock()
        for statement in _TABLES:
            self.run(statement)

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.lock:
            cursor = self.connection.execute(self._sql(sql), params)
            return cursor.fetchall() if cursor.description else []

    def run(self, sql: str, params: tuple = ()) -> int:
        """Execute a write and return how many rows it changed."""
        with self.lock:
            return self.connection.execute(self._sql(sql), params).rowcount

    def close(self) -> None:
        self.connection.close()

    def _sql(self, sql: str) -> str:
        # Queries are written with SQLite's ? placeholders; psycopg uses %s.
        return sql.replace("?", "%s") if self.postgres else sql

    # Conversations: each belongs to one user, listed by latest activity.

    def new_thread(self, user_id: str) -> str:
        # No "/" so the id can sit in a URL path.
        thread_id = f"{user_id}.{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
        now = _now()
        self.run("INSERT INTO threads VALUES (?, ?, '', ?, ?)", (thread_id, user_id, now, now))
        return thread_id

    def threads(self, user_id: str) -> list[dict]:
        rows = self.rows(
            "SELECT thread_id, title, created_at, updated_at FROM threads WHERE user_id = ? "
            "ORDER BY updated_at DESC, created_at DESC",
            (user_id,),
        )
        return [dict(zip(("id", "title", "created_at", "updated_at"), row)) for row in rows]

    def owns(self, user_id: str, thread_id: str) -> bool:
        return bool(self.rows("SELECT 1 FROM threads WHERE thread_id = ? AND user_id = ?", (thread_id, user_id)))

    def touch(self, thread_id: str, message: str) -> None:
        """Record activity; the first message becomes the title."""
        self.run(
            "UPDATE threads SET updated_at = ?, title = CASE WHEN title = '' THEN ? ELSE title END WHERE thread_id = ?",
            (_now(), " ".join(message.split())[:20], thread_id),
        )

    def forget_thread(self, thread_id: str) -> None:
        self.run("DELETE FROM threads WHERE thread_id = ?", (thread_id,))

    def latest_thread(self, user_id: str) -> str | None:
        threads = self.threads(user_id)
        return threads[0]["id"] if threads else None


def open_storage():
    """The Storage for the agent's tables and a checkpointer for conversation states."""
    if use_postgres():
        return _open_postgres()
    return open_sqlite(DEFAULT_PATH)


def open_sqlite(path: Path | str):
    connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30, isolation_level=None)
    # WAL lets several request threads read while one writes.
    connection.execute("PRAGMA journal_mode=WAL")
    saver_connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    return Storage(connection), SqliteSaver(saver_connection, serde=serializer())


def memory_storage() -> Storage:
    """An in-memory Storage for tests."""
    return Storage(sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None))


def _open_postgres():
    # Imported only here: SQLite users do not need the Postgres packages installed.
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row

    settings = postgres_settings()
    with Connection.connect(**settings, autocommit=True) as setup:
        setup.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    # Every table, LangGraph's checkpoint tables included, is created inside the agent schema.
    in_schema = {**settings, "autocommit": True, "options": f"-c search_path={SCHEMA}"}
    saver = PostgresSaver(
        Connection.connect(**in_schema, prepare_threshold=0, row_factory=dict_row),
        serde=serializer(),
    )
    saver.setup()
    return Storage(Connection.connect(**in_schema), postgres=True), saver


def _now() -> str:
    # Milliseconds so conversations used within the same second still sort by activity.
    return datetime.now().isoformat(timespec="milliseconds")
