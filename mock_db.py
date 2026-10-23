"""Test databases: the backend's PostgreSQL code run on known listings.

Tests use the database <DB_NAME>_test on the server in .env, made on first use (the account needs
the right to create databases). Each set of listings has its own schema there, made with the
pipeline's own table scripts:

- mock: the 12 made-up listings in tests/fixtures/mock_listings.json, made again for every test,
  since tests change them;
- real: the group's data in output-final-delivery, loaded by load_data.py and sync_v2.py, with
  commute_faculty.csv, once per test run;
- storage: accounts and conversations (empty_storage()).

Every call also empties what the backend writes there, link checks and accounts, so tests do not
see each other's. Without a reachable PostgreSQL the tests that need one are skipped with the
reason; the others still run.
"""

import atexit
import csv
import json
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from build_commutes import COMMUTE_DATA, import_commutes
from config import postgres_settings
from group_db import Database, connect, ensure_database, open_pool, prepare
from sessions import Storage
from setup_database import SCRIPT_FOLDER, TABLE_SCRIPTS

ROOT = Path(__file__).parent
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "mock_listings.json"
# The tables the backend writes; emptied for every test.
_AGENT_TABLES = ("listing_health", "listing_route_enrichment", "place_routes")
# Listing fields kept in listing_enrichment rather than listings (migration_v2.sql).
_ENRICHMENT = {
    "enriched_at", "postcode", "street_name", "latitude", "longitude", "poi_hawker_1km", "poi_library_1km",
    "poi_sport_1km", "poi_healthcare_1km", "poi_community_1km", "poi_fnb_1km", "pg_school_count",
    "pg_school_nearest_walk_m", "pg_school_nearest_walk_min", "pg_mrt_count", "pg_mrt_nearest_walk_m",
    "coord_source", "coord_error_m",
}
_pools: dict[str, ConnectionPool] = {}
_ready: set[str] = set()
_unavailable: list[str] = []


def create_mock_database(path: Path = DEFAULT_FIXTURE) -> Database:
    """The made-up listings, as new; their links are already checked (active unless the fixture says not)."""
    source = json.loads(path.read_text(encoding="utf-8"))["listings"]
    payload = _legacy_payload(source)
    commutes = [
        {"listing_id": row["listing_id"], "faculty": faculty, "minutes": trip["minutes"], "mode": trip["mode"], "departure": ""}
        for row in source
        for faculty, trip in (row.get("commutes") or {}).items()
    ]
    checked_at = datetime.now(timezone.utc).isoformat()
    health = [
        {
            "listing_id": row["listing_id"],
            "status": "active" if row.get("listing_status_code") == "ACT" else "inactive",
            "checked_at": checked_at,
            "final_url": row.get("url"),
        }
        for row in source
    ]
    with _new_schema("mock") as pg:
        for table in ("district_lookup", "listings", "listing_metadata"):
            _insert(pg, table, payload[table])
        _import_commutes(pg, commutes)
        prepare(pg, "mock")
        _insert(pg, "listing_health", health)
    return Database(_pool("mock"), owns_pool=False)


def create_database(commute_path: Path = COMMUTE_DATA) -> Database:
    """The group's V2 listings as the pipeline loads them, with commutes from commute_path."""
    if "real" not in _ready:
        with _new_schema("real"):
            pass
        # The pipeline's own loaders, writing to this schema.
        sys.path.insert(0, str(ROOT / "src"))
        from dss5105.data import load_data, sync_v2

        for module in (load_data, sync_v2):
            module.get_connection = lambda: connect("real", dbname=database_name(), autocommit=False)
            with redirect_stdout(StringIO()):
                module.main()
        with connect("real", dbname=database_name()) as pg, pg.transaction():
            import_commutes(pg, COMMUTE_DATA)
            prepare(pg, "real")
            _analyze(pg)
        _ready.add("real")
    if commute_path == COMMUTE_DATA:
        with _pool("real").connection() as pg:
            pg.execute(f"TRUNCATE {', '.join(_AGENT_TABLES)}")
        return Database(_pool("real"), owns_pool=False)
    # Other commutes: the same listings in a schema of their own.
    with _new_schema("commutes") as pg:
        for table in ("district_lookup", "listings", "listing_enrichment", "listing_metadata"):
            pg.execute(f"INSERT INTO {table} SELECT * FROM real.{table}")
        if commute_path.exists():
            import_commutes(pg, commute_path)
        prepare(pg, "commutes")
    return Database(_pool("commutes"), owns_pool=False)


def empty_storage() -> Storage:
    """Accounts, conversations, kept profiles and LangGraph checkpoints, all empty."""
    pool = _pool("storage")
    with pool.connection() as pg:
        tables = [row["tablename"] for row in pg.execute(
            # Which LangGraph migrations ran stays, so its tables are not made again.
            "SELECT tablename FROM pg_tables WHERE schemaname = 'storage' AND tablename <> 'checkpoint_migrations'"
        )]
        if tables:
            pg.execute(f"TRUNCATE {', '.join(tables)}")
    return Storage(Database(pool, owns_pool=False))


def reopened(schema: str) -> Database:
    """A new pool on a test schema, as a restarted server makes; close it after use."""
    _pool(schema)
    return Database(open_pool(schema, dbname=database_name()))


def plain_connection(schema: str) -> psycopg.Connection:
    """A connection with rows as tuples, as scripts such as build_commutes.py use."""
    _pool(schema)
    return connect(schema, dbname=database_name())


def set_listing(database: Database, listing_id: str, **fields) -> None:
    """Change a test listing's fields in whichever pipeline table holds each."""
    for field, value in fields.items():
        if field in _ENRICHMENT:
            database.run(
                f"INSERT INTO listing_enrichment (listing_id, {field}) VALUES (%s, %s) "
                f"ON CONFLICT (listing_id) DO UPDATE SET {field} = EXCLUDED.{field}",
                (listing_id, value),
            )
        else:
            database.run(f"UPDATE listings SET {field} = %s WHERE listing_id = %s", (value, listing_id))


def database_name() -> str:
    """The test database: DB_NAME in .env with _test after it."""
    name = postgres_settings()["dbname"]
    if not name:
        _skip("没有在 .env 里配置 DB_NAME 等数据库连接")
    return f"{name}_test"


def _skip(reason: str):
    _unavailable.append(reason)
    raise unittest.SkipTest(reason)


def _pool(schema: str) -> ConnectionPool:
    if _unavailable:
        raise unittest.SkipTest(_unavailable[0])
    if schema not in _pools:
        name = database_name()
        try:
            ensure_database(name)
            with connect("public", dbname=name) as pg:
                pg.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            _pools[schema] = open_pool(schema, dbname=name)
        except psycopg.Error as error:
            _skip(f"测试数据库 {name} 用不了：{error}")
    return _pools[schema]


@contextmanager
def _new_schema(schema: str):
    """schema emptied and given the pipeline's tables; yields a plain connection to it, committed at the end."""
    _pool(schema)
    with connect(schema, dbname=database_name()) as pg, pg.transaction():
        pg.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        pg.execute(f"CREATE SCHEMA {schema}")
        for script, _, _ in TABLE_SCRIPTS:
            pg.execute((SCRIPT_FOLDER / script).read_text(encoding="utf-8"))
        yield pg
        _analyze(pg)


def _analyze(pg: psycopg.Connection) -> None:
    """Statistics for the schema's new rows, so the planner does not guess (as setup_database.py does)."""
    for (table,) in pg.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()").fetchall():
        pg.execute(f"ANALYZE {table}")


def _insert(pg: psycopg.Connection, table: str, rows: list[dict]) -> None:
    """Rows into table, with the columns it has."""
    if not rows:
        return
    columns = [name for (name,) in pg.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    )]
    columns = [column for column in columns if column in rows[0]]
    with pg.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('%s' for _ in columns)})",
            [[row.get(column) for column in columns] for row in rows],
        )


def _import_commutes(pg: psycopg.Connection, rows: list[dict]) -> None:
    """Commutes through build_commutes.import_commutes, from a CSV like commute_faculty.csv."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "commute_faculty.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=("listing_id", "faculty", "minutes", "mode", "departure"))
            writer.writeheader()
            writer.writerows(rows)
        import_commutes(pg, path)


@atexit.register
def _close() -> None:
    for pool in _pools.values():
        pool.close()


def _legacy_payload(rows: list[dict]) -> dict:
    listings = []
    metadata = []
    districts = {}
    for row in rows:
        text = f"{row.get('title', '')} {row.get('card_text', '')}".casefold()
        area_sqft = _non_negative(row.get("floor_area_sqft"))
        listings.append(
            {
                "listing_id": str(row["listing_id"]),
                "title": row["title"],
                "listing_url": row["url"],
                "rent_monthly_sgd": row["price_sgd"],
                "rent_price_type": _rent_price_type(row.get("price_terms")),
                "rental_scope": _snake(row.get("rental_scope")),
                "room_type": _snake(row.get("room_type")),
                "property_type": _snake(row.get("property_type")),
                "bedrooms": _non_negative(row.get("bedrooms")),
                "bathrooms": _non_negative(row.get("bathrooms")),
                "area_sqm": round(area_sqft * 0.09290304, 2) if area_sqft else None,
                "area_scope": "floor_reported" if area_sqft else "unknown",
                "district_code": row["district_code"],
                "address": row["address"],
                "mrt_station": row.get("mrt_station") or "unknown",
                "mrt_distance_m": row.get("mrt_distance_m"),
                "mrt_minutes_reported": row.get("mrt_minutes_reported"),
                "mrt_operation_status": "unknown",
                "listed_date": row["posted_at_text"],
                "collected_at": row["collected_at"],
                "tenant_count_reported": None,
                "tenant_gender_label": "unknown",
                "gender_restriction": (
                    "female_only" if "female tenant only" in text else "unknown"
                ),
                "gender_preference": (
                    "male" if "male tenant preferred" in text else "unknown"
                ),
                "cooking_policy": _cooking_policy(text),
                "furnishing": "unknown",
                "landlord_lives_in": (
                    "no"
                    if "no owner staying" in text
                    else "yes"
                    if "owner staying" in text
                    else "unknown"
                ),
                "private_bathroom": (
                    "yes" if "attached bathroom" in text else "unknown"
                ),
                "air_conditioning": "unknown",
                "pets_policy": "unknown",
                "rent_monthly_sgd_now": None,
                "scrape_status": "active",
                "lease_term": row.get("lease_term"),
            }
        )
        metadata.append(
            {
                "listing_id": str(row["listing_id"]),
                "availability_status": _availability_status(
                    row.get("availability_text")
                ),
                "review_flags": row["review_flags"],
            }
        )
        districts[row["district_code"]] = row["district"]
    return {
        "listings": listings,
        "listing_metadata": metadata,
        "district_lookup": [
            {"district_code": code, "district": name}
            for code, name in sorted(districts.items())
        ],
    }


def _snake(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text or text == "unknown":
        return "unknown"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _non_negative(value: object):
    return value if isinstance(value, (int, float)) and value >= 0 else None


def _rent_price_type(value: object) -> str:
    normalized = _snake(value)
    return normalized if normalized in {"negotiable", "starting_from"} else "asking"


def _cooking_policy(text: str) -> str:
    if "no cooking" in text:
        return "not_allowed"
    if "light cooking" in text or "cooking allowed twice" in text:
        return "light_only"
    if "cooking allowed" in text:
        return "allowed"
    return "unknown"


def _availability_status(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text == "available now":
        return "ready_at_snapshot"
    if text.startswith("available from "):
        return "date_missing_year"
    return "unknown"
