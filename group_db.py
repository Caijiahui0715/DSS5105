"""The project's PostgreSQL, the only database the backend uses.

Connection settings are DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD in .env, shared with the
data pipeline; setup_database.py fills a new database in one go.

- public: the listing tables, written only by the data pipeline (src/dss5105/data, build_commutes.py).
- agent: written only by the backend: accounts, conversations and kept profiles (sessions.py,
  accounts.py, profiles.py), LangGraph's checkpoints, link checks, and the agent_listings view that
  every search reads.

The view is made again at every start, so changing it needs no migration, and it reads the
pipeline's tables as they are: a data refresh shows from the next query, without a restart.
"""

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import missing_db_settings, postgres_settings
from models import AMENITY_FIELDS

SCHEMA = "agent"
UNAVAILABLE = "The database cannot be reached right now. Try again in a moment."
_SETUP_HINT = "Run python setup_database.py first."
_SQM_PER_SQFT = 0.09290304
# V2 labels mapped to the V1 values that search filters and reply templates use.
_V1_LABELS = {
    "cooking_policy": {
        "light_cooking": "light_only",
        "cooking_any_cooking": "allowed",
        "cooking_not_allowed": "not_allowed",
        "cooking_prefer_not_to_say": "unknown",
    },
    "pets_policy": {"no_pets": "not_allowed", "pets_allowed": "allowed"},
}
_TEXT = (
    "listing_id", "title", "listing_url", "rent_price_type", "rental_scope", "room_type", "property_type",
    "area_scope", "district_code", "address", "mrt_station", "mrt_operation_status", "tenant_gender_label",
    "gender_restriction", "gender_preference", "furnishing", "landlord_lives_in", "private_bathroom",
    "air_conditioning", "scrape_status", "lease_term",
)
_INTEGER = ("bedrooms", "bathrooms", "mrt_minutes_reported", "tenant_count_reported", *(f"poi_{name}_1km" for name in (
    "hawker", "library", "sport", "healthcare", "community", "fnb")), "pg_school_count", "pg_mrt_count")
# NUMERIC columns that hold whole numbers, read as integers as the V2 data states them.
_WHOLE = ("pg_school_nearest_walk_m", "pg_school_nearest_walk_min", "pg_mrt_nearest_walk_m")
_ENRICHMENT_TEXT = ("postcode", "street_name", "coord_source")


def _labels(field: str) -> str:
    cases = " ".join(f"WHEN '{v2}' THEN '{v1}'" for v2, v1 in _V1_LABELS[field].items())
    return f"CASE a.{field} {cases} ELSE a.{field} END AS {field}"


def _position(field: str) -> str:
    """Position among the listings stating field: 0 has the most, 1 the fewest; ties share a position."""
    return (
        f"CASE WHEN {field} IS NOT NULL THEN "
        f"1 - (rank() OVER (ORDER BY {field}) - 1)::float8 / count({field}) OVER () END"
    )


# Every search reads this view. Ranks are relative to every active listing, so they are computed
# over all of them before any search condition applies. Numbers come back as Python int or float
# and dates as ISO text, as the listing cards and ranking expect.
AGENT_LISTINGS = f"""
WITH active AS (
    SELECT l.*, {', '.join(f'e.{field}' for field in (
        'enriched_at', 'postcode', 'street_name', 'latitude', 'longitude', 'poi_hawker_1km', 'poi_library_1km',
        'poi_sport_1km', 'poi_healthcare_1km', 'poi_community_1km', 'poi_fnb_1km', 'pg_school_count',
        'pg_school_nearest_walk_m', 'pg_school_nearest_walk_min', 'pg_mrt_count', 'pg_mrt_nearest_walk_m',
        'coord_source', 'coord_error_m'))},
        -- Nearby F&B and hawker centres, each by position, averaged over the counts stated.
        {_position('e.poi_fnb_1km')} AS fnb_position,
        {_position('e.poi_hawker_1km')} AS hawker_position,
        {', '.join(f"{_position(f'e.{field}')} AS {name}_rank" for name, field in AMENITY_FIELDS.items())}
    FROM listings l
    LEFT JOIN listing_enrichment e USING (listing_id)
    WHERE l.scrape_status = 'active'
),
-- Area percentile within the same rental scope, among listings whose area is the rented space.
space AS (
    SELECT listing_id, percent_rank() OVER (PARTITION BY rental_scope, area_scope ORDER BY area_sqm DESC) AS space_rank
    FROM active
    WHERE area_sqm > 0 AND (
        (rental_scope = 'entire_unit' AND area_scope = 'floor_reported') OR
        (rental_scope = 'room' AND area_scope = 'room_reported')
    )
)
SELECT
    {', '.join(f'a.{field}' for field in _TEXT if field not in _V1_LABELS)},
    {_labels('cooking_policy')},
    {_labels('pets_policy')},
    {', '.join(f'a.{field}::int AS {field}' for field in _INTEGER)},
    {', '.join(f'round(a.{field})::int AS {field}' for field in _WHOLE)},
    {', '.join(f'a.{field}' for field in _ENRICHMENT_TEXT)},
    a.area_sqm::float8 AS area_sqm,
    a.mrt_distance_m::float8 AS mrt_distance_m,
    a.coord_error_m::float8 AS coord_error_m,
    a.latitude::float8 AS latitude,
    a.longitude::float8 AS longitude,
    a.listed_date::text AS listed_date,
    replace(a.collected_at::text, ' ', 'T') AS collected_at,
    replace(a.enriched_at::text, ' ', 'T') AS enriched_at,
    round(((coalesce(a.fnb_position, 0) + coalesce(a.hawker_position, 0)) / nullif(
        (a.fnb_position IS NOT NULL)::int + (a.hawker_position IS NOT NULL)::int, 0))::numeric, 3)::float8 AS food_rank,
    coalesce(c.commutes, '{{}}'::jsonb) AS commutes,
    coalesce(p.place_commutes, '{{}}'::jsonb) AS place_commutes,
    -- Up to six photo links from the V2 data (migration_photos.sql), the home's own first.
    coalesce(a.photos, '{{}}'::text[]) AS photos,
    s.space_rank,
    {', '.join(f'a.{name}_rank' for name in AMENITY_FIELDS)},
    -- The agent uses the rechecked rent when V2 has one; the card rent stays for evidence.
    coalesce(a.rent_monthly_sgd_now, a.rent_monthly_sgd)::float8 AS rent_monthly_sgd,
    a.rent_monthly_sgd::float8 AS rent_monthly_sgd_card,
    a.rent_monthly_sgd_now::float8 AS rent_monthly_sgd_now,
    d.district,
    coalesce(m.availability_status, 'unknown') AS availability_status,
    -- V1 area flags predate the V2 room areas; only the under-80 sqft rule is checked again.
    array_remove(coalesce(m.review_flags, '{{}}'), 'area_outside_review_range')
        || CASE WHEN round(a.area_sqm / {_SQM_PER_SQFT}) < 80 THEN ARRAY['area_outside_review_range'] ELSE '{{}}'::text[] END
        AS review_flags,
    coalesce(h.status, 'unknown') AS live_status,
    h.checked_at AS live_checked_at,
    h.final_url,
    h.http_status,
    h.error_reason AS live_error_reason,
    r.mrt_walk_distance_m,
    r.mrt_walk_seconds,
    r.mrt_walk_minutes
FROM active a
LEFT JOIN space s USING (listing_id)
-- {{"School of Computing": {{"minutes": 23, "mode": "transit"}}, ...}}: the faster trip to each faculty,
-- walking only when strictly faster, as build_commutes.py decides. Made per listing, so a search
-- reads only the commutes of the listings meeting its conditions.
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(faculty_name, jsonb_build_object('minutes', minutes, 'mode', mode)) AS commutes
    FROM (
        SELECT DISTINCT ON (d.faculty_name)
            d.faculty_name, t.duration_min::float8 AS minutes,
            CASE WHEN t.travel_mode = 'walk' THEN 'walk' WHEN t.route_provider = 'google' THEN 'transit_google' ELSE 'transit' END AS mode
        FROM listing_commutes t
        JOIN nus_destinations d USING (destination_id)
        WHERE t.listing_id = a.listing_id AND t.duration_min IS NOT NULL
        ORDER BY d.faculty_name, t.duration_min, t.travel_mode = 'walk'
    ) trips
) c ON TRUE
-- {{"1.28520,103.82720": {{"minutes": 18, "mode": "transit"}}, ...}}: routes to the places users named
-- (place_routes.py), by place; a place with no route has no entry.
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(place_key, jsonb_build_object('minutes', minutes, 'mode', mode)) AS place_commutes
    FROM place_routes WHERE listing_id = a.listing_id AND minutes IS NOT NULL
) p ON TRUE
LEFT JOIN listing_metadata m USING (listing_id)
LEFT JOIN district_lookup d USING (district_code)
LEFT JOIN listing_health h USING (listing_id)
LEFT JOIN listing_route_enrichment r USING (listing_id)
"""
# The backend's own tables next to the view; no foreign keys, so the pipeline can rebuild listings freely.
_TABLES = (
    # Link checks, reused for 24 hours across restarts (tools.validate_ranked_listings).
    "CREATE TABLE IF NOT EXISTS {schema}.listing_health ("
    "listing_id TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL, "
    "final_url TEXT, http_status INTEGER, error_reason TEXT)",
    # OneMap walking routes to the listed MRT station (tools.refresh_mrt_walk_data).
    "CREATE TABLE IF NOT EXISTS {schema}.listing_route_enrichment ("
    "listing_id TEXT PRIMARY KEY, mrt_walk_distance_m INTEGER, mrt_walk_seconds INTEGER, "
    "mrt_walk_minutes INTEGER, checked_at TEXT NOT NULL)",
    # OneMap routes to a place a user named as the other destination, worked out on first use and
    # kept (place_routes.py); minutes is null when OneMap has no route.
    "CREATE TABLE IF NOT EXISTS {schema}.place_routes ("
    "place_key TEXT NOT NULL, listing_id TEXT NOT NULL, minutes DOUBLE PRECISION, mode TEXT, "
    "departure TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY (place_key, listing_id))",
)


def _session(schema: str) -> dict:
    path = schema if schema == "public" else f"{schema},public"
    return {
        "autocommit": True,
        # Tables the backend creates go to its schema; the pipeline's are found in public. A query
        # never hangs a turn for long.
        "options": f"-c search_path={path} -c statement_timeout=15000",
        # A silently dropped connection is noticed.
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }


def connect(schema: str = SCHEMA, **settings) -> psycopg.Connection:
    """One plain connection, rows as tuples, for scripts such as build_commutes.py."""
    return psycopg.Connection.connect(**{**postgres_settings(), **_session(schema), **settings})


class Database:
    """Connections shared by request threads. A query on a lost connection raises
    psycopg.OperationalError, which ends that turn with UNAVAILABLE; the pool connects again for
    the next one."""

    def __init__(self, pool: ConnectionPool, owns_pool: bool = True):
        self.pool, self._owns_pool = pool, owns_pool

    def query(self, sql: str, params=None) -> list[dict]:
        with self.pool.connection() as connection:
            cursor = connection.execute(sql, params)
            return cursor.fetchall() if cursor.description else []

    def run(self, sql: str, params=None) -> int:
        """Execute a write and return how many rows it changed."""
        with self.pool.connection() as connection:
            return connection.execute(sql, params).rowcount

    def close(self) -> None:
        if self._owns_pool:
            self.pool.close()


def open_pool(schema: str = SCHEMA, **settings) -> ConnectionPool:
    settings = {**postgres_settings(), **settings}
    timeout = float(settings["connect_timeout"])
    pool = ConnectionPool(
        # LangGraph's PostgresSaver shares the pool. No prepared statements: after another program
        # makes the view again with other columns, a prepared query would fail until a restart.
        kwargs={**settings, **_session(schema), "row_factory": dict_row, "prepare_threshold": None},
        min_size=1,
        max_size=10,
        # How long a query waits for a connection before the turn gives up.
        timeout=timeout,
        # A connection the server dropped while idle is replaced before use.
        check=ConnectionPool.check_connection,
        open=False,
    )
    try:
        pool.open(wait=True, timeout=timeout)
    except psycopg.Error:
        # Otherwise it keeps trying to connect in the background.
        pool.close()
        raise
    return pool


def prepare(connection: psycopg.Connection, schema: str = SCHEMA) -> None:
    """Make the backend's tables and the agent_listings view in schema, reading the listing tables
    found on the connection's search path."""
    with connection.transaction():
        for statement in _TABLES:
            connection.execute(statement.format(schema=schema))
        connection.execute(f"DROP VIEW IF EXISTS {schema}.agent_listings")
        connection.execute(f"CREATE VIEW {schema}.agent_listings AS {AGENT_LISTINGS}")


def ensure_database(name: str) -> bool:
    """Create the database name on the server in .env unless it exists; True when created."""
    try:
        connect("public", dbname=name).close()
        return False
    except psycopg.OperationalError:
        # Perhaps it does not exist yet; the server's own database can tell.
        pass
    with connect("public", dbname="postgres") as server:
        if server.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            # It exists, so the first error was something else; connecting again shows it.
            connect("public", dbname=name).close()
            return False
        server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return True


def open_database() -> Database:
    """The database for the backend, ready to search; stops the program with what to fix otherwise."""
    settings = postgres_settings()
    if problem := missing_db_settings():
        raise SystemExit(problem)
    place = f"{settings['dbname']} on {settings['host']}:{settings['port']}"
    try:
        # A plain connection first: its error says why, where the pool would only time out.
        with connect() as connection:
            # Made only when missing: an account without the right to create schemas can still use it.
            if connection.execute("SELECT to_regnamespace(%s) IS NULL", (SCHEMA,)).fetchone()[0]:
                connection.execute(f"CREATE SCHEMA {SCHEMA}")
        database = Database(open_pool())
    except psycopg.OperationalError as error:
        raise SystemExit(
            f"Cannot connect to PostgreSQL ({place}): {error}\n"
            "Check that the PostgreSQL service is running, and DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD in .env."
        ) from error
    except psycopg.Error as error:
        raise SystemExit(f"Cannot create the {SCHEMA} schema in PostgreSQL ({place}): {error}\nCheck DB_USER's rights in this database.") from error
    try:
        with database.pool.connection() as connection:
            prepare(connection)
        listings = database.query("SELECT count(*) AS n FROM agent_listings")[0]["n"]
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as error:
        database.close()
        raise SystemExit(f"The listing tables in {place} are incomplete ({error.diag.message_primary}). {_SETUP_HINT}") from error
    except psycopg.Error as error:
        database.close()
        raise SystemExit(f"Could not prepare the agent_listings view in {place}: {error}") from error
    if not listings:
        database.close()
        raise SystemExit(f"{place} has no usable listings (scrape_status = 'active'). {_SETUP_HINT}")
    return database
