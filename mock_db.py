import csv
import json
import re
import sqlite3
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

from models import AMENITY_FIELDS


ROOT = Path(__file__).parent
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "mock_listings.json"
DEFAULT_FINAL_DATA = ROOT / "output-final-delivery" / "rental_data_v2.csv"
# V2 only replaces the listings table; availability, review flags and districts stay in V1.
V1_DATA = ROOT / "output-final-delivery" / "rental_data_v1.json"
# Optional: minutes from each listing to each NUS faculty by public transport, or on foot when
# that is faster (columns listing_id, faculty, minutes, mode, departure), made by
# build_commutes.py with OneMap. Without the file every commute is unknown.
COMMUTE_DATA = ROOT / "commute_faculty.csv"
_SQM_PER_SQFT = 0.09290304
# Nearby food is ranked on these V2 counts; see _food_ranks().
_FOOD_FIELDS = ("poi_fnb_1km", "poi_hawker_1km")
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
    "rent_monthly_sgd_now",
    "scrape_status",
    "enriched_at",
    "postcode",
    "street_name",
    "latitude",
    "longitude",
    "poi_hawker_1km",
    "poi_library_1km",
    "poi_sport_1km",
    "poi_healthcare_1km",
    "poi_community_1km",
    "pg_school_count",
    "pg_school_nearest_walk_m",
    "pg_school_nearest_walk_min",
    "pg_mrt_count",
    "pg_mrt_nearest_walk_m",
    "coord_source",
    "coord_error_m",
    "poi_fnb_1km",
)
# Not V2 columns: food_rank is derived at load time (see _food_ranks()), the commute comes from COMMUTE_DATA.
FOOD_RANK_FIELD = "food_rank"
# Trips to each faculty as JSON, {"School of Computing": {"minutes": 23, "mode": "transit"}, ...};
# see tools.commute().
COMMUTE_FIELD = "commutes"
_AMENITY_RANKS = tuple(f"{name}_rank" for name in AMENITY_FIELDS)
_COLUMNS = (*LISTING_FIELDS, FOOD_RANK_FIELD, COMMUTE_FIELD)


def create_database(
    path: Path = DEFAULT_FINAL_DATA,
    commute_path: Path = COMMUTE_DATA,
) -> sqlite3.Connection:
    """Load the V2 listings CSV, with V1 metadata and districts, into in-memory SQLite."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [field for field in LISTING_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
        # Empty cells become NULL; column affinity turns numeric text into numbers.
        listings = [
            {field: value or None for field, value in row.items()}
            for row in reader
        ]
    for listing in listings:
        for field, labels in _V1_LABELS.items():
            listing[field] = labels.get(listing[field], listing[field])
    ranks = _food_ranks(listings)
    commutes = _commutes(commute_path)
    for listing in listings:
        listing[FOOD_RANK_FIELD] = ranks.get(listing["listing_id"])
        listing[COMMUTE_FIELD] = json.dumps(commutes.get(listing["listing_id"], {}), ensure_ascii=False)
    v1 = json.loads(V1_DATA.read_text(encoding="utf-8"))
    metadata = {row["listing_id"]: row for row in v1["listing_metadata"]}
    return _create_database(
        {
            "listings": listings,
            "listing_metadata": [
                _v2_metadata(listing, metadata.get(listing["listing_id"]))
                for listing in listings
            ],
            "district_lookup": v1["district_lookup"],
        }
    )


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
    # Scores are based on the full dataset, so search, comparison and explanation agree.
    for name, field in AMENITY_FIELDS.items():
        values = sorted(float(row[field]) for row in payload["listings"] if row.get(field) is not None)
        for row in payload["listings"]:
            value = row.get(field)
            row[f"{name}_rank"] = 1 - bisect_left(values, float(value)) / len(values) if value is not None else None
    # The web server shares this read-mostly database across its request threads.
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.execute("PRAGMA foreign_keys = ON")
    view_columns = ", ".join(
        f"l.{field}" for field in _COLUMNS if field != "rent_monthly_sgd"
    )
    connection.executescript(
        f"""
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
            pets_policy TEXT NOT NULL,
            rent_monthly_sgd_now REAL,
            scrape_status TEXT,
            enriched_at TEXT,
            postcode TEXT,
            street_name TEXT,
            latitude REAL,
            longitude REAL,
            poi_hawker_1km INTEGER,
            poi_library_1km INTEGER,
            poi_sport_1km INTEGER,
            poi_healthcare_1km INTEGER,
            poi_community_1km INTEGER,
            pg_school_count INTEGER,
            pg_school_nearest_walk_m INTEGER,
            pg_school_nearest_walk_min INTEGER,
            pg_mrt_count INTEGER,
            pg_mrt_nearest_walk_m INTEGER,
            coord_source TEXT,
            coord_error_m REAL,
            poi_fnb_1km INTEGER,
            food_rank REAL,
            commutes TEXT
        );

        CREATE TABLE listing_amenity_ranks (
            listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
            {', '.join(f'{field} REAL' for field in _AMENITY_RANKS)}
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
            {view_columns},
            a.space_rank,
            {', '.join(f'q.{field}' for field in _AMENITY_RANKS)},
            -- The agent uses the rechecked rent when V2 has one; the card rent stays for evidence.
            COALESCE(l.rent_monthly_sgd_now, l.rent_monthly_sgd) AS rent_monthly_sgd,
            l.rent_monthly_sgd AS rent_monthly_sgd_card,
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
        -- Compute area ranks separately so the view keeps its existing listing order.
        LEFT JOIN (
            SELECT listing_id, PERCENT_RANK() OVER (
                PARTITION BY rental_scope, area_scope ORDER BY area_sqm DESC
            ) AS space_rank
            FROM listings
            WHERE area_sqm > 0 AND (
                (rental_scope = 'entire_unit' AND area_scope = 'floor_reported') OR
                (rental_scope = 'room' AND area_scope = 'room_reported')
            )
        ) a USING (listing_id)
        LEFT JOIN listing_amenity_ranks q USING (listing_id)
        LEFT JOIN listing_metadata m USING (listing_id)
        LEFT JOIN district_lookup d USING (district_code)
        LEFT JOIN listing_health h USING (listing_id)
        LEFT JOIN listing_route_enrichment r USING (listing_id);
        """
    )
    placeholders = ", ".join("?" for _ in _COLUMNS)
    with connection:
        connection.executemany(
            f"INSERT INTO listings ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [[row.get(field) for field in _COLUMNS] for row in payload["listings"]],
        )
        connection.executemany(
            f"INSERT INTO listing_amenity_ranks VALUES ({', '.join('?' for _ in range(1 + len(_AMENITY_RANKS)))})",
            [[row["listing_id"], *(row[field] for field in _AMENITY_RANKS)] for row in payload["listings"]],
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


def _food_ranks(listings: list[dict]) -> dict[str, float]:
    """Rank listings by nearby food: 0 has the most choice, 1 the least.

    Counts of very different size (F&B 3-1395, hawker centres 0-8) are compared
    by position among the listings that state them, then averaged.
    """
    positions: dict[str, list[float]] = {}
    for field in _FOOD_FIELDS:
        counts = sorted(float(row[field]) for row in listings if row.get(field) is not None)
        for row in listings:
            value = row.get(field)
            if value is not None:
                share = bisect_left(counts, float(value)) / len(counts)
                positions.setdefault(row["listing_id"], []).append(1 - share)
    return {
        listing_id: round(sum(shares) / len(shares), 3)
        for listing_id, shares in positions.items()
    }


def _commutes(path: Path) -> dict[str, dict[str, dict]]:
    commutes: dict[str, dict[str, dict]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if row["minutes"]:
                    # Files from before walking checks have no mode: every time is by public transport.
                    trip = {"minutes": float(row["minutes"]), "mode": row.get("mode") or "transit"}
                    commutes.setdefault(row["listing_id"], {})[row["faculty"]] = trip
    except FileNotFoundError:
        pass
    return commutes


def _v2_metadata(listing: dict, metadata: dict | None) -> dict:
    metadata = metadata or {"availability_status": "unknown", "review_flags": []}
    # V1 area flags predate the V2 room areas; re-check only the under-80 sqft rule.
    flags = [flag for flag in metadata["review_flags"] if flag != "area_outside_review_range"]
    area = listing["area_sqm"]
    if area is not None and round(float(area) / _SQM_PER_SQFT) < 80:
        flags.append("area_outside_review_range")
    return {
        "listing_id": listing["listing_id"],
        "availability_status": metadata["availability_status"],
        "review_flags": flags,
    }


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
                "scrape_status": None,
                "enriched_at": None,
                # Made-up commute minutes for tests.
                "commutes": json.dumps(row.get("commutes") or {}, ensure_ascii=False),
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
