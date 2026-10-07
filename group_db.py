"""The group's PostgreSQL as the agent's data source (AGENT_DB=postgres in .env).

The data pipeline fills the listing tables in the public schema (src/dss5105/database,
src/dss5105/data/sync_v2.py) and build_commutes.py the commute tables there. The agent reads them
into the same in-memory SQLite that the CSV builds, so search, ranking and explanations work
unchanged, and rebuilds that copy when the data changes. What the agent writes itself, accounts,
conversations and link checks, lives in the agent schema (see sessions.py).
"""

import logging
import threading
from datetime import date
from decimal import Decimal
from time import monotonic

from config import postgres_settings, use_postgres
from mock_db import LISTING_FIELDS, create_database, listing_database

# How often a running server compares the group database with what it loaded.
CHECK_EVERY_SECONDS = 300
# After the database fails twice in a row, it is left alone this long, so link checks and turns
# do not each wait for the connection timeout.
PAUSE_AFTER_FAILURE_SECONDS = 60

_LISTINGS = """
    SELECT * FROM public.listings
    LEFT JOIN public.listing_enrichment USING (listing_id)
    LEFT JOIN public.listing_metadata USING (listing_id)
    WHERE scrape_status = 'active'
    ORDER BY listing_id
"""
_DISTRICTS = "SELECT district_code, district FROM public.district_lookup"
_COMMUTES = """
    SELECT c.listing_id, d.faculty_name, c.travel_mode, c.route_provider, c.duration_min
    FROM public.listing_commutes c JOIN public.nus_destinations d USING (destination_id)
    WHERE c.duration_min IS NOT NULL
"""
_HEALTH = "SELECT listing_id, status, checked_at, final_url, http_status, error_reason FROM agent.listing_health"
# One short value standing for everything loaded above; any change to that data changes it.
_FINGERPRINT = """
    SELECT md5(string_agg(row_hash, '' ORDER BY row_hash)) FROM (
        SELECT md5(l::text || coalesce(e::text, '') || coalesce(m::text, '')) AS row_hash
        FROM public.listings l
        LEFT JOIN public.listing_enrichment e USING (listing_id)
        LEFT JOIN public.listing_metadata m USING (listing_id)
        WHERE l.scrape_status = 'active'
        UNION ALL SELECT md5(d::text) FROM public.district_lookup d
        UNION ALL SELECT md5(c::text) FROM public.listing_commutes c
        UNION ALL SELECT md5(n::text) FROM public.nus_destinations n
    ) loaded
"""
_SETUP = (
    "CREATE SCHEMA IF NOT EXISTS agent",
    # Link checks by the agent, kept across restarts; no foreign key, so the pipeline can rebuild
    # the listing tables freely.
    "CREATE TABLE IF NOT EXISTS agent.listing_health ("
    "listing_id TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL, "
    "final_url TEXT, http_status INTEGER, error_reason TEXT)",
)
_SAVE_HEALTH = """
    INSERT INTO agent.listing_health VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (listing_id) DO UPDATE SET
        status = EXCLUDED.status,
        checked_at = EXCLUDED.checked_at,
        final_url = EXCLUDED.final_url,
        http_status = EXCLUDED.http_status,
        error_reason = EXCLUDED.error_reason
"""


def open_listings():
    """The listings for this setup: the group's PostgreSQL with AGENT_DB=postgres, otherwise the CSV.

    A configured database that cannot be read stops the program instead of silently falling back
    to the files, so it is always clear which data is in use.
    """
    if not use_postgres():
        return create_database()
    try:
        return LiveListings()
    except Exception as error:
        raise SystemExit(
            f"读不到组里的 PostgreSQL（.env 设了 AGENT_DB=postgres）：{error}\n"
            "检查 DB_HOST、DB_NAME 等连接设置；不用数据库时去掉 AGENT_DB 即可改用本地文件。"
        ) from error


def connect():
    # Imported here: without AGENT_DB=postgres the Postgres packages are not needed.
    from psycopg import Connection

    return Connection.connect(
        **postgres_settings(),
        autocommit=True,
        # A query never hangs a turn for long, and a silently dropped connection is noticed.
        options="-c statement_timeout=15000",
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )


def load(pg):
    """Build the in-memory listings database from PostgreSQL; returns it and the data's fingerprint."""
    # Read first: data changed while loading then shows up as a new fingerprint at the next check.
    fingerprint = pg.execute(_FINGERPRINT).fetchone()[0]
    listings, metadata = [], {}
    for row in _dicts(pg.execute(_LISTINGS)):
        listings.append({field: _plain(row.get(field)) for field in LISTING_FIELDS})
        if row.get("availability_status") is not None:
            metadata[row["listing_id"]] = {
                "availability_status": row["availability_status"],
                "review_flags": list(row.get("review_flags") or []),
            }
    districts = [{"district_code": code, "district": name} for code, name in pg.execute(_DISTRICTS)]
    commutes: dict[str, dict[str, dict]] = {}
    for listing_id, faculty, travel_mode, provider, minutes in pg.execute(_COMMUTES):
        mode = "walk" if travel_mode == "walk" else "transit_google" if provider == "google" else "transit"
        trips = commutes.setdefault(listing_id, {})
        trip = {"minutes": float(minutes), "mode": mode}
        if faster(trip, trips.get(faculty)):
            trips[faculty] = trip
    health = [tuple(_plain(value) for value in row) for row in pg.execute(_HEALTH)]
    return listing_database(listings, metadata, districts, commutes, health), fingerprint


def faster(trip: dict, known: dict | None) -> bool:
    """Whether trip beats the one known so far; walking wins only when strictly faster, as build_commutes.py decides."""
    if known is None:
        return True
    if trip["minutes"] != known["minutes"]:
        return trip["minutes"] < known["minutes"]
    return known["mode"] == "walk"


class LiveListings:
    """The listings read from the group's PostgreSQL, rebuilt whole when the data there changes.

    Used like the sqlite3 connection it holds. A rebuild makes a complete new copy and then swaps
    it in, because some values (facility and food ranks) are relative to every listing.
    """

    def __init__(self, connect=connect, every: float = CHECK_EVERY_SECONDS):
        self._connect, self._every = connect, every
        self._lock = threading.Lock()
        self._paused_until = 0.0
        self._pg, self._retired = connect(), None
        for statement in _SETUP:
            self._pg.execute(statement)
        self.connection, self.fingerprint = load(self._pg)
        self._checked = monotonic()

    def __getattr__(self, name):
        # Only called for names this class lacks; "connection" itself missing means loading failed.
        if name == "connection":
            raise AttributeError(name)
        return getattr(self.connection, name)

    def __enter__(self):
        return self.connection.__enter__()

    def __exit__(self, *exc):
        return self.connection.__exit__(*exc)

    def refresh(self, force: bool = False) -> bool:
        """Rebuild if the data changed; checks at most every few minutes unless forced. True when rebuilt."""
        with self._lock:
            if not force and monotonic() - self._checked < self._every:
                return False
            self._checked = monotonic()
            try:
                if self._run(lambda pg: pg.execute(_FINGERPRINT).fetchone()[0]) == self.fingerprint:
                    return False
                connection, fingerprint = self._run(load)
            except Exception as error:
                logging.warning("could not check the group database, still using the data loaded earlier: %s", error)
                return False
            # A request may still be reading the copy just replaced, so it is closed one reload later.
            if self._retired is not None:
                self._retired.close()
            self._retired, self.connection, self.fingerprint = self.connection, connection, fingerprint
            logging.info("reloaded the listings from the group database")
            return True

    def save_listing_health(self, listing_id: str, health: dict) -> None:
        """Keep a link check in agent.listing_health so later runs reuse it."""
        row = (listing_id, *(health[field] for field in ("status", "checked_at", "final_url", "http_status", "error_reason")))
        with self._lock:
            try:
                self._run(lambda pg: pg.execute(_SAVE_HEALTH, row))
            except Exception as error:
                # The check is still used from memory; only its reuse after a restart is lost.
                logging.warning("could not save a link check to the group database: %s", error)

    def close(self) -> None:
        for connection in (self.connection, self._retired):
            if connection is not None:
                connection.close()
        self._drop()

    def _run(self, work):
        """work(connection), tried once more on a new connection: a cloud database may have closed an
        idle one, which only shows when it is used."""
        if monotonic() < self._paused_until:
            raise ConnectionError("the group database failed less than a minute ago")
        for attempt in (1, 2):
            try:
                if self._pg is None or self._pg.closed:
                    self._pg = self._connect()
                return work(self._pg)
            except Exception:
                self._drop()
                if attempt == 2:
                    self._paused_until = monotonic() + PAUSE_AFTER_FAILURE_SECONDS
                    raise

    def _drop(self) -> None:
        if self._pg is not None:
            self._pg.close()
        self._pg = None


def _dicts(cursor) -> list[dict]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def _plain(value):
    """PostgreSQL values as the CSV gives them: numbers as floats, dates and times as ISO text."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
