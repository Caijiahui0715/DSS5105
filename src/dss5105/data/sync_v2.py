from pathlib import Path
from typing import Any

import pandas as pd

from dss5105.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[3]

ACTIVE_FILE = (
    PROJECT_ROOT
    / "output-final-delivery"
    / "rental_data_v2.csv"
)

REMOVED_FILE = (
    PROJECT_ROOT
    / "output-final-delivery"
    / "removed_listings.csv"
)


# ---------------------------------------------------------
# Columns stored in the main listings table
# ---------------------------------------------------------

LISTING_COLUMNS = [
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
    # Added by migration_lease_term.sql; run it before this script.
    "lease_term",
]


# ---------------------------------------------------------
# Columns stored in listing_enrichment
# ---------------------------------------------------------

ENRICHMENT_COLUMNS = [
    "listing_id",
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
    "poi_fnb_1km",
    "pg_school_count",
    "pg_school_nearest_walk_m",
    "pg_school_nearest_walk_min",
    "pg_mrt_count",
    "pg_mrt_nearest_walk_m",
    "coord_source",
    "coord_error_m",
]


def clean_value(value: Any) -> Any:
    """
    Convert pandas/numpy missing values into Python None
    so PostgreSQL stores them as SQL NULL.
    """

    if pd.isna(value):
        return None

    # Convert numpy scalar types to ordinary Python values
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            pass

    return value


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """
    Convert a DataFrame into clean Python dictionaries.
    """

    records = []

    for row in df.to_dict(orient="records"):
        cleaned = {
            key: clean_value(value)
            for key, value in row.items()
        }
        records.append(cleaned)

    return records


def build_upsert_query(
    table_name: str,
    columns: list[str],
    conflict_column: str,
) -> str:
    """
    Build a reusable INSERT ... ON CONFLICT DO UPDATE query.
    """

    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    update_columns = [
        column
        for column in columns
        if column != conflict_column
    ]

    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in update_columns
    )

    return f"""
        INSERT INTO {table_name} (
            {column_sql}
        )
        VALUES (
            {placeholders}
        )
        ON CONFLICT ({conflict_column})
        DO UPDATE SET
            {update_sql};
    """


def upsert_active_listings(cur, records: list[dict]) -> None:
    query = build_upsert_query(
        table_name="listings",
        columns=LISTING_COLUMNS,
        conflict_column="listing_id",
    )

    for row in records:
        values = [
            row.get(column)
            for column in LISTING_COLUMNS
        ]

        cur.execute(query, values)


def upsert_enrichment(cur, records: list[dict]) -> None:
    query = build_upsert_query(
        table_name="listing_enrichment",
        columns=ENRICHMENT_COLUMNS,
        conflict_column="listing_id",
    )

    for row in records:
        values = [
            row.get(column)
            for column in ENRICHMENT_COLUMNS
        ]

        cur.execute(query, values)


def mark_removed_listings(
    cur,
    removed_records: list[dict],
) -> int:
    """
    Mark listings found in removed_listings.csv as removed.
    We keep the historical listing instead of deleting it.
    """

    query = """
        UPDATE listings
        SET
            scrape_status = 'removed',
            rent_monthly_sgd_now = NULL
        WHERE listing_id = %s;
    """

    updated = 0

    for row in removed_records:
        cur.execute(
            query,
            (row["listing_id"],),
        )

        updated += cur.rowcount

    return updated


def main():
    print("Reading V2 data...")

    active_df = pd.read_csv(
        ACTIVE_FILE,
        dtype={
            "listing_id": str,
            "postcode": str,
        },
    )

    removed_df = pd.read_csv(
        REMOVED_FILE,
        dtype={
            "listing_id": str,
        },
    )

    # Two street-level geocodes record their error as "~500", which the NUMERIC column refuses;
    # coord_source already says they are approximate.
    active_df["coord_error_m"] = pd.to_numeric(
        active_df["coord_error_m"].astype("string").str.lstrip("~")
    )

    active_records = dataframe_to_records(active_df)
    removed_records = dataframe_to_records(removed_df)

    print(f"Active V2 rows: {len(active_records)}")
    print(f"Removed rows: {len(removed_records)}")

    with get_connection() as conn:
        with conn.cursor() as cur:

            print("\nUpdating active listings...")
            upsert_active_listings(
                cur,
                active_records,
            )

            print("Updating enrichment data...")
            upsert_enrichment(
                cur,
                active_records,
            )

            print("Marking removed listings...")
            removed_updated = mark_removed_listings(
                cur,
                removed_records,
            )

        conn.commit()

    print("\nV2 synchronization completed.")
    print(f"Removed listings updated: {removed_updated}")


if __name__ == "__main__":
    main()