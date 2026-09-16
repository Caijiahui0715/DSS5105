import json
from pathlib import Path

from dss5105.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = PROJECT_ROOT / "output-final-delivery" / "rental_data_v1.json"

EXPECTED_SCHEMA_VERSION = "1.0"


def load_json():
    """Load the V1 rental data handoff file."""

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise ValueError(
            f"Unexpected schema version: {data.get('schema_version')}. "
            f"Expected {EXPECTED_SCHEMA_VERSION}."
        )

    return data


def insert_districts(cur, districts):
    query = """
        INSERT INTO district_lookup (
            district_code,
            district
        )
        VALUES (%s, %s)
        ON CONFLICT (district_code) DO UPDATE
        SET district = EXCLUDED.district;
    """

    for row in districts:
        cur.execute(
            query,
            (
                row["district_code"],
                row["district"],
            ),
        )


def insert_listings(cur, listings):
    query = """
        INSERT INTO listings (
            listing_id,
            title,
            listing_url,
            rent_monthly_sgd,
            rent_price_type,
            rental_scope,
            room_type,
            property_type,
            bedrooms,
            bathrooms,
            area_sqm,
            area_scope,
            district_code,
            address,
            mrt_station,
            mrt_distance_m,
            mrt_minutes_reported,
            mrt_operation_status,
            listed_date,
            collected_at,
            tenant_count_reported,
            tenant_gender_label,
            gender_restriction,
            gender_preference,
            cooking_policy,
            furnishing,
            landlord_lives_in,
            private_bathroom,
            air_conditioning,
            pets_policy
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (listing_id) DO UPDATE
        SET
            title = EXCLUDED.title,
            listing_url = EXCLUDED.listing_url,
            rent_monthly_sgd = EXCLUDED.rent_monthly_sgd,
            rent_price_type = EXCLUDED.rent_price_type,
            rental_scope = EXCLUDED.rental_scope,
            room_type = EXCLUDED.room_type,
            property_type = EXCLUDED.property_type,
            bedrooms = EXCLUDED.bedrooms,
            bathrooms = EXCLUDED.bathrooms,
            area_sqm = EXCLUDED.area_sqm,
            area_scope = EXCLUDED.area_scope,
            district_code = EXCLUDED.district_code,
            address = EXCLUDED.address,
            mrt_station = EXCLUDED.mrt_station,
            mrt_distance_m = EXCLUDED.mrt_distance_m,
            mrt_minutes_reported = EXCLUDED.mrt_minutes_reported,
            mrt_operation_status = EXCLUDED.mrt_operation_status,
            listed_date = EXCLUDED.listed_date,
            collected_at = EXCLUDED.collected_at,
            tenant_count_reported = EXCLUDED.tenant_count_reported,
            tenant_gender_label = EXCLUDED.tenant_gender_label,
            gender_restriction = EXCLUDED.gender_restriction,
            gender_preference = EXCLUDED.gender_preference,
            cooking_policy = EXCLUDED.cooking_policy,
            furnishing = EXCLUDED.furnishing,
            landlord_lives_in = EXCLUDED.landlord_lives_in,
            private_bathroom = EXCLUDED.private_bathroom,
            air_conditioning = EXCLUDED.air_conditioning,
            pets_policy = EXCLUDED.pets_policy;
    """

    for row in listings:
        cur.execute(
            query,
            (
                row["listing_id"],
                row["title"],
                row["listing_url"],
                row["rent_monthly_sgd"],
                row["rent_price_type"],
                row["rental_scope"],
                row["room_type"],
                row["property_type"],
                row["bedrooms"],
                row["bathrooms"],
                row["area_sqm"],
                row["area_scope"],
                row["district_code"],
                row["address"],
                row["mrt_station"],
                row["mrt_distance_m"],
                row["mrt_minutes_reported"],
                row["mrt_operation_status"],
                row["listed_date"],
                row["collected_at"],
                row["tenant_count_reported"],
                row["tenant_gender_label"],
                row["gender_restriction"],
                row["gender_preference"],
                row["cooking_policy"],
                row["furnishing"],
                row["landlord_lives_in"],
                row["private_bathroom"],
                row["air_conditioning"],
                row["pets_policy"],
            ),
        )


def insert_metadata(cur, metadata):
    query = """
        INSERT INTO listing_metadata (
            listing_id,
            availability_status,
            review_flags
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (listing_id) DO UPDATE
        SET
            availability_status = EXCLUDED.availability_status,
            review_flags = EXCLUDED.review_flags;
    """

    for row in metadata:
        cur.execute(
            query,
            (
                row["listing_id"],
                row["availability_status"],
                row["review_flags"],
            ),
        )


def main():
    data = load_json()

    print("Loaded JSON file.")
    print(f"Schema version: {data['schema_version']}")
    print(f"Districts: {len(data['district_lookup'])}")
    print(f"Listings: {len(data['listings'])}")
    print(f"Metadata rows: {len(data['listing_metadata'])}")

    with get_connection() as conn:
        with conn.cursor() as cur:

            print("\nLoading district_lookup...")
            insert_districts(cur, data["district_lookup"])

            print("Loading listings...")
            insert_listings(cur, data["listings"])

            print("Loading listing_metadata...")
            insert_metadata(cur, data["listing_metadata"])

        conn.commit()

    print("\nData load completed successfully.")


if __name__ == "__main__":
    main()