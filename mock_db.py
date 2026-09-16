import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parent
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "mock_listings.json"
DEFAULT_FINAL_DATA = ROOT / "output-final-delivery" / "rental_data_v1.json"

LISTING_FIELDS = (
    "listing_id",
    "title",
    "listing_url",
    "rent_monthly_sgd",
    "rent_price_type",
    "rental_scope",
    "room_type",
    "property_type",
    "bedrooms",
    "bathrooms",
    "area_sqm",
    "area_scope",
    "district_code",
    "address",
    "mrt_station",
    "mrt_distance_m",
    "mrt_minutes_reported",
    "mrt_operation_status",
    "listed_date",
    "collected_at",
    "tenant_count_reported",
    "tenant_gender_label",
    "gender_restriction",
    "gender_preference",
    "cooking_policy",
    "furnishing",
    "landlord_lives_in",
    "private_bathroom",
    "air_conditioning",
    "pets_policy",
)


def create_database(path: Path = DEFAULT_FINAL_DATA) -> sqlite3.Connection:
    """Load the frozen V1 JSON contract into an in-memory SQLite database."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _create_database(payload)


def create_mock_database(path: Path = DEFAULT_FIXTURE) -> sqlite3.Connection:
    """Adapt the small legacy fixture to the frozen V1 schema for fast tests."""
    source = json.loads(path.read_text(encoding="utf-8"))["listings"]
    connection = _create_database(_legacy_payload(source))
    checked_at = datetime.now(timezone.utc).isoformat()
    with connection:
        connection.executemany(
            """
            INSERT INTO listing_health (listing_id, status, checked_at, final_url)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    row["listing_id"],
                    "active" if row.get("listing_status_code") == "ACT" else "inactive",
                    checked_at,
                    row.get("url"),
                )
                for row in source
            ],
        )
    return connection


def _create_database(payload: dict) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE listings (
            listing_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            listing_url TEXT NOT NULL UNIQUE,
            rent_monthly_sgd REAL NOT NULL,
            rent_price_type TEXT NOT NULL,
            rental_scope TEXT NOT NULL,
            room_type TEXT NOT NULL,
            property_type TEXT NOT NULL,
            bedrooms INTEGER,
            bathrooms INTEGER,
            area_sqm REAL,
            area_scope TEXT NOT NULL,
            district_code TEXT NOT NULL,
            address TEXT NOT NULL,
            mrt_station TEXT NOT NULL,
            mrt_distance_m REAL,
            mrt_minutes_reported INTEGER,
            mrt_operation_status TEXT NOT NULL,
            listed_date TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            tenant_count_reported INTEGER,
            tenant_gender_label TEXT NOT NULL,
            gender_restriction TEXT NOT NULL,
            gender_preference TEXT NOT NULL,
            cooking_policy TEXT NOT NULL,
            furnishing TEXT NOT NULL,
            landlord_lives_in TEXT NOT NULL,
            private_bathroom TEXT NOT NULL,
            air_conditioning TEXT NOT NULL,
            pets_policy TEXT NOT NULL
        );

        CREATE TABLE listing_metadata (
            listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
            availability_status TEXT NOT NULL,
            review_flags TEXT NOT NULL
        );

        CREATE TABLE district_lookup (
            district_code TEXT PRIMARY KEY,
            district TEXT NOT NULL
        );

        CREATE TABLE listing_health (
            listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
            status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'unknown')),
            checked_at TEXT NOT NULL,
            final_url TEXT,
            http_status INTEGER,
            error_reason TEXT
        );

        CREATE TABLE listing_route_enrichment (
            listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
            mrt_walk_distance_m INTEGER,
            mrt_walk_seconds INTEGER,
            mrt_walk_minutes INTEGER,
            checked_at TEXT NOT NULL
        );

        CREATE VIEW agent_listings AS
        SELECT
            l.*,
            d.district,
            m.availability_status,
            m.review_flags,
            COALESCE(h.status, 'unknown') AS live_status,
            h.checked_at AS live_checked_at,
            h.final_url,
            h.http_status,
            h.error_reason AS live_error_reason,
            r.mrt_walk_distance_m,
            r.mrt_walk_seconds,
            r.mrt_walk_minutes
        FROM listings l
        LEFT JOIN listing_metadata m USING (listing_id)
        LEFT JOIN district_lookup d USING (district_code)
        LEFT JOIN listing_health h USING (listing_id)
        LEFT JOIN listing_route_enrichment r USING (listing_id);
        """
    )
    placeholders = ", ".join("?" for _ in LISTING_FIELDS)
    with connection:
        connection.executemany(
            f"INSERT INTO listings ({', '.join(LISTING_FIELDS)}) VALUES ({placeholders})",
            [[row[field] for field in LISTING_FIELDS] for row in payload["listings"]],
        )
        connection.executemany(
            "INSERT INTO listing_metadata VALUES (?, ?, ?)",
            [
                (
                    row["listing_id"],
                    row["availability_status"],
                    json.dumps(row["review_flags"]),
                )
                for row in payload["listing_metadata"]
            ],
        )
        connection.executemany(
            "INSERT INTO district_lookup VALUES (?, ?)",
            [
                (row["district_code"], row["district"])
                for row in payload["district_lookup"]
            ],
        )
    return connection


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
        "schema_version": "1.0-test-adapter",
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
