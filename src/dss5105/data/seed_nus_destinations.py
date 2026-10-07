from pathlib import Path
import csv

from dss5105.database.connection import get_connection

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = PROJECT_ROOT / "data" / "nus_destinations_geocoded.csv"

UPSERT_SQL = """
INSERT INTO nus_destinations (
    destination_id,
    faculty_code,
    faculty_name,
    destination_name,
    address,
    postal_code,
    campus_area,
    latitude,
    longitude,
    is_default
)
VALUES (
    %(destination_id)s,
    %(faculty_code)s,
    %(faculty_name)s,
    %(destination_name)s,
    %(address)s,
    %(postal_code)s,
    %(campus_area)s,
    %(latitude)s,
    %(longitude)s,
    %(is_default)s
)
ON CONFLICT (faculty_code)
DO UPDATE SET
    destination_id = EXCLUDED.destination_id,
    faculty_name = EXCLUDED.faculty_name,
    destination_name = EXCLUDED.destination_name,
    address = EXCLUDED.address,
    postal_code = EXCLUDED.postal_code,
    campus_area = EXCLUDED.campus_area,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    is_default = EXCLUDED.is_default;
"""

def optional_float(value: str):
    value = (value or "").strip()
    return float(value) if value else None

def to_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "y"}

def main():
    with DATA_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    with get_connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                code = row["faculty_code"].strip()
                params = {
                    "destination_id": f"{code.lower()}_default",
                    "faculty_code": code,
                    "faculty_name": row["faculty_name"].strip(),
                    "destination_name": row["destination_name"].strip(),
                    "address": row["address"].strip(),
                    "postal_code": row["postal_code"].strip() or None,
                    "campus_area": row["campus_area"].strip() or None,
                    "latitude": optional_float(row["latitude"]),
                    "longitude": optional_float(row["longitude"]),
                    "is_default": to_bool(row["is_default"]),
                }
                cur.execute(UPSERT_SQL, params)
        conn.commit()

    print(f"Seeded {len(rows)} NUS representative destinations.")

if __name__ == "__main__":
    main()
