import json
import sqlite3
from pathlib import Path


DEFAULT_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "mock_listings.json"


def create_mock_database(path: Path = DEFAULT_FIXTURE) -> sqlite3.Connection:
    rows = json.loads(path.read_text(encoding="utf-8"))["listings"]
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE listings (
            listing_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            listing_status_code TEXT NOT NULL,
            platform_verified INTEGER,
            availability_text TEXT,
            collected_at TEXT,
            price_sgd INTEGER,
            room_type TEXT,
            district_code TEXT,
            address TEXT,
            mrt_station TEXT,
            mrt_minutes_reported INTEGER,
            mrt_walk_distance_m INTEGER,
            mrt_walk_seconds INTEGER,
            mrt_walk_minutes INTEGER,
            card_text TEXT NOT NULL,
            review_flags TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO listings (
            listing_id, title, listing_status_code, platform_verified,
            availability_text, collected_at,
            price_sgd, room_type, district_code, address, mrt_station,
            mrt_minutes_reported, mrt_walk_distance_m, mrt_walk_seconds,
            mrt_walk_minutes, card_text, review_flags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["listing_id"],
                row["title"],
                row["listing_status_code"],
                row["platform_verified"],
                row["availability_text"],
                row["collected_at"],
                row["price_sgd"],
                row["room_type"],
                row["district_code"],
                row["address"],
                row["mrt_station"],
                row["mrt_minutes_reported"],
                None,
                None,
                None,
                row["card_text"],
                json.dumps(row["review_flags"]),
            )
            for row in rows
        ],
    )
    return connection
